import argparse
import sys
import json

# 修复在Windows控制台打印带有特殊化学字符(₀₁₂₃等)时的 GBK/cp1252 编码崩溃问题
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding='utf-8')

from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from config import config
from tools.llm_utils import build_gemini_llm
from tools.neo4j_utils import neo4j_tool
from tools.chem_utils import check_charge_balance, suggest_common_oxidation_states

class AgentState(TypedDict, total=False):
    user_query: str
    objective: str
    min_fwhm: Optional[float]
    min_plqy: Optional[float]
    constraint_source: str
    constraint_policy: Dict[str, Any]
    candidates: List[Dict[str, Any]]
    evidence: Dict[str, List[Dict[str, Any]]]
    draft_answer: str
    novel_candidates: List[Dict[str, Any]]
    feedback: str
    final_answer: str
    retry_count: int


def _llm_content_to_text(content: Any) -> str:
    """Normalize LangChain model outputs into a plain string for robust parsing."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _load_system_prompt(filename: str, required: bool = False) -> str:
    path = Path(config.BASE_DIR) / "prompts" / filename
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required prompt file not found: {path}")
        return ""

    prompt = path.read_text(encoding="utf-8").strip()
    if required and not prompt:
        raise ValueError(f"Required prompt file is empty: {path}")
    return prompt


def _to_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first balanced JSON object from free-form model output."""
    if not text:
        return None

    start = -1
    depth = 0
    in_string = False
    escape = False

    for idx, ch in enumerate(text):
        if start == -1:
            if ch == "{":
                start = idx
                depth = 1
            continue

        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    return None


def planner_node(state: AgentState) -> AgentState:
    llm = build_gemini_llm(temperature=0.1)
    user_query = state.get("user_query", "Recommend copper halide candidates for broadband white light")

    prompt = (
        "Analyze the user query and extract requested performance constraints along with a short objective.\n"
        "If a metric is not explicitly requested, output null for that metric.\n"
        "Output ONLY valid JSON like: {\"objective\": \"...\", \"min_fwhm\": null, \"min_plqy\": null}\n"
        f"User query: {user_query}"
    )
    response = llm.invoke(prompt)
    res = _llm_content_to_text(getattr(response, "content", response))
    
    objective = user_query
    min_fwhm = None
    min_plqy = None
    
    try:
        json_obj = _extract_first_json_object(res)
        if json_obj:
            data = json.loads(json_obj)
            objective = data.get("objective", user_query)
            min_fwhm = _to_optional_float(data.get("min_fwhm"))
            min_plqy = _to_optional_float(data.get("min_plqy"))
    except Exception:
        pass

    return {
        "objective": str(objective).strip(),
        "min_fwhm": min_fwhm,
        "min_plqy": min_plqy,
        "constraint_source": "user" if (min_fwhm is not None or min_plqy is not None) else "pending",
        "retry_count": state.get("retry_count", 0)
    }


def constraint_builder_node(state: AgentState) -> AgentState:
    objective = state.get("objective", "")
    user_fwhm_opt = state.get("min_fwhm")
    user_plqy_opt = state.get("min_plqy")

    if not config.DYNAMIC_CONSTRAINTS:
        final_fwhm = user_fwhm_opt if user_fwhm_opt is not None else 80.0
        final_plqy = user_plqy_opt if user_plqy_opt is not None else 10.0
        source = "user" if (user_fwhm_opt is not None or user_plqy_opt is not None) else "fallback"
        return {
            "min_fwhm": float(final_fwhm),
            "min_plqy": float(final_plqy),
            "constraint_source": source,
            "constraint_policy": {
                "dynamic_constraints": False,
                "fallback_defaults": {"min_fwhm": 80.0, "min_plqy": 10.0},
            },
        }

    suggestion = neo4j_tool.suggest_white_light_constraints(
        objective=objective,
        user_min_fwhm=user_fwhm_opt,
        user_min_plqy=user_plqy_opt,
        fallback_min_fwhm=80.0,
        fallback_min_plqy=10.0,
    )

    return {
        "min_fwhm": suggestion["min_fwhm"],
        "min_plqy": suggestion["min_plqy"],
        "constraint_source": suggestion.get("source", "kg"),
        "constraint_policy": {
            "dynamic_constraints": True,
            "policy": suggestion.get("policy", {}),
        },
    }


def retriever_node(state: AgentState) -> AgentState:
    min_fwhm = state.get("min_fwhm")
    min_plqy = state.get("min_plqy")
    if min_fwhm is None:
        min_fwhm = 80.0
    if min_plqy is None:
        min_plqy = 10.0
    candidates = neo4j_tool.find_white_light_candidates(limit=5, min_fwhm=min_fwhm, min_plqy=min_plqy)
    evidence: Dict[str, List[Dict[str, Any]]] = {}

    for row in candidates:
        formula = row["formula"]
        evidence[formula] = neo4j_tool.get_material_evidence(
            formula=formula,
            target_properties=["fwhm", "plqy", "stability", "pl_wavelength", "cie_coordinates"],
        )

    return {"candidates": candidates, "evidence": evidence}


def reasoner_node(state: AgentState) -> AgentState:
    llm = build_gemini_llm(temperature=0.2)
    system_prompt = _load_system_prompt("novel_candidate_prompt.txt", required=True)

    payload = {
        "objective": state.get("objective"),
        "known_formulas": [c["formula"] for c in state.get("candidates", [])],
        "evidence": state.get("evidence", {}),
        "critic_feedback": state.get("feedback", "")
    }

    prompt = (
        f"{system_prompt}\n\n"
        "Generate out-of-KG novel candidates using the JSON schema provided in your system instructions.\n"
        f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    response = llm.invoke(prompt)
    draft = _llm_content_to_text(getattr(response, "content", response))
    novel_cands = []
    try:
        json_obj = _extract_first_json_object(draft)
        if json_obj:
            parsed = json.loads(json_obj)
            novel_cands = parsed.get("novel_candidates", [])
    except Exception:
        pass

    return {"draft_answer": draft.strip(), "novel_candidates": novel_cands}


def critic_node(state: AgentState) -> AgentState:
    novel_candidates = state.get("novel_candidates", [])
    draft = state.get("draft_answer", "")
    retry_count = state.get("retry_count", 0)

    if not novel_candidates:
        return {"retry_count": retry_count + 1, "feedback": "Failed to generate novel candidates or output valid JSON."}

    all_valid = True
    feedback_msgs = []

    for cand in novel_candidates:
        formula = cand.get("formula", "")
        if not formula:
            continue
        try:
            import re
            # Pre-process formula to prevent pymatgen parsing errors
            # 1. Convert unicode subscripts/superscripts to standard ASCII
            clean_f = formula.translate(str.maketrans("₀₁₂₃₄₅₆₇₈₉⁺⁻", "0123456789+-"))
            # 2. Strip out dopant declarations like " (0.2% In)", ":Ag", " (x% Tl)"
            # 修改正则：仅截断处于空格后的圆括号（如掺杂说明）或冒号后的掺杂，而不误杀开头的合法配合物圆括号
            clean_f = re.sub(r'(?:\s+\(.*|:.*)$', '', clean_f)
            # 再清理掉可能残留的空格
            clean_f = clean_f.replace(' ', '')

            # Simplistic assignment of common oxidation states to test validity
            suggestions = suggest_common_oxidation_states(clean_f)
            # Prioritize standard oxidation states for common elements in this domain: Cu(+1), Halides(-1), Alkali(+1)
            ox_states = {}
            for el, states in suggestions.items():
                # 强制铜基卤化物发光材料中的 Cu 以 +1 价计算电荷平衡
                if el == "Cu": ox_states[el] = 1
                elif el in ["I", "Br", "Cl", "F"] and -1 in states: ox_states[el] = -1
                elif states: ox_states[el] = states[0]
                else: ox_states[el] = 0

            res = check_charge_balance(clean_f, ox_states)
            if not res["is_balanced"]:
                all_valid = False
                feedback_msgs.append(f"Formula {clean_f} (from {formula}) fails charge balance. Calculated total charge: {res['total_charge']}.")
        except Exception as e:
            all_valid = False
            feedback_msgs.append(f"Formula {formula} validation error: {str(e)}")

    if not all_valid:
        with open("chem_intercept_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[INTERCEPT] Retry Count: {retry_count} | Feedback: {'; '.join(feedback_msgs)}\n")
        # 验证失败，返回反馈信息和重试次数，触发重试循环
        return {"retry_count": retry_count + 1, "feedback": "\n".join(feedback_msgs)}

    # 验证全部通过，输出最终答案并结束
    return {"final_answer": draft}


def route_after_critic(state: AgentState) -> str:
    if state.get("final_answer"):
        return END
    if state.get("retry_count", 0) >= 2:
        return END
    return "reasoner"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("constraint_builder", constraint_builder_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("reasoner", reasoner_node)
    graph.add_node("critic", critic_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "constraint_builder")
    graph.add_edge("constraint_builder", "retriever")
    graph.add_edge("retriever", "reasoner")
    graph.add_edge("reasoner", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"reasoner": "reasoner", END: END})

    return graph.compile()


def run_agent(user_query: str) -> str:
    app = build_graph()
    result = app.invoke({"user_query": user_query})
    return result.get("final_answer") or result.get("draft_answer") or "No result generated."


def save_output_to_json(output_str: str, filepath: str = "generated_candidates.json") -> None:
    try:
        json_obj = _extract_first_json_object(output_str)
        if not json_obj:
            print("\n[-] No valid JSON found in the output to save.")
            return
        
        new_data = json.loads(json_obj)
        p = Path(filepath)
        
        existing_data = []
        if p.exists():
            try:
                existing_data = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(existing_data, list):
                    existing_data = [existing_data]
            except Exception:
                pass
                
        existing_data.append(new_data)
        p.write_text(json.dumps(existing_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[+] Results successfully appended to {filepath}")
    except Exception as e:
        print(f"\n[-] Failed to save results to JSON: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Copper halide white-light LangGraph agent")
    parser.add_argument("query", nargs="?", default="Recommend broadband white-light copper halide candidates")
    args = parser.parse_args()

    try:
        output = run_agent(args.query)
        print(output)
        save_output_to_json(output)
    finally:
        neo4j_tool.close()


if __name__ == "__main__":
    main()
