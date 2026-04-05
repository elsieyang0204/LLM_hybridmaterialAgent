import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

from config import config
from tools.llm_utils import build_gemini_llm
from tools.neo4j_utils import neo4j_tool
from tools.chem_utils import check_charge_balance, suggest_common_oxidation_states

class AgentState(TypedDict, total=False):
    user_query: str
    objective: str
    min_fwhm: float
    min_plqy: float
    candidates: List[Dict[str, Any]]
    evidence: Dict[str, List[Dict[str, Any]]]
    draft_answer: str
    novel_candidates: List[Dict[str, Any]]
    feedback: str
    final_answer: str
    retry_count: int


def _load_system_prompt(filename: str) -> str:
    path = Path("prompts") / filename
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def planner_node(state: AgentState) -> AgentState:
    llm = build_gemini_llm(temperature=0.1)
    user_query = state.get("user_query", "Recommend copper halide candidates for broadband white light")

    prompt = (
        "Analyze the user query and extract the required performance metrics along with a short objective. "
        "FWHM defaults to 80 and PLQY defaults to 10 if not explicitly mentioned.\n"
        "Output ONLY valid JSON like: {\"objective\": \"...\", \"min_fwhm\": 80, \"min_plqy\": 10}\n"
        f"User query: {user_query}"
    )
    res = llm.invoke(prompt).content
    
    objective = user_query
    min_fwhm = 80.0
    min_plqy = 10.0
    
    try:
        json_match = re.search(r'\{.*\}', res, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(0))
            objective = data.get("objective", user_query)
            min_fwhm = float(data.get("min_fwhm", 80.0))
            min_plqy = float(data.get("min_plqy", 10.0))
    except Exception:
        pass

    return {
        "objective": str(objective).strip(),
        "min_fwhm": min_fwhm,
        "min_plqy": min_plqy,
        "retry_count": state.get("retry_count", 0)
    }


def retriever_node(state: AgentState) -> AgentState:
    min_fwhm = state.get("min_fwhm", 80.0)
    min_plqy = state.get("min_plqy", 10.0)
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
    system_prompt = _load_system_prompt("novel_candidate_prompt.txt")

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

    draft = llm.invoke(prompt).content
    novel_cands = []
    try:
        json_match = re.search(r'\{.*\}', draft, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group(0))
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
            # Simplistic assignment of common oxidation states to test validity
            suggestions = suggest_common_oxidation_states(formula)
            # Prioritize standard oxidation states for common elements in this domain: Cu(+1), Halides(-1), Alkali(+1)
            ox_states = {}
            for el, states in suggestions.items():
                if el == "Cu" and 1 in states: ox_states[el] = 1
                elif el in ["I", "Br", "Cl", "F"] and -1 in states: ox_states[el] = -1
                elif states: ox_states[el] = states[0]
                else: ox_states[el] = 0

            res = check_charge_balance(formula, ox_states)
            if not res["is_balanced"]:
                all_valid = False
                feedback_msgs.append(f"Formula {formula} fails charge balance. Calculated total charge: {res['total_charge']}.")
        except Exception as e:
            all_valid = False
            feedback_msgs.append(f"Formula {formula} chemical parsing error: {str(e)}.")

    # Logging intercepts and failures
    if not all_valid:
        with open("chem_intercept_log.txt", "a", encoding="utf-8") as f:
            f.write(f"[INTERCEPT] Retry Count: {retry_count} | Feedback: {'; '.join(feedback_msgs)}\n")
        return {"final_answer": draft}

    return {"retry_count": retry_count + 1, "feedback": "\n".join(feedback_msgs)}


def route_after_critic(state: AgentState) -> str:
    if state.get("final_answer"):
        return END
    if state.get("retry_count", 0) >= 2:
        return END
    return "reasoner"


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("planner", planner_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("reasoner", reasoner_node)
    graph.add_node("critic", critic_node)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "retriever")
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
        json_match = re.search(r'\{.*\}', output_str, re.DOTALL)
        if not json_match:
            print("\n[-] No valid JSON found in the output to save.")
            return
        
        new_data = json.loads(json_match.group(0))
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
