import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, TypedDict

from langgraph.graph import END, START, StateGraph

from config import config
from tools.llm_utils import build_gemini_llm
from tools.neo4j_utils import neo4j_tool


class AgentState(TypedDict, total=False):
    user_query: str
    objective: str
    candidates: List[Dict[str, Any]]
    evidence: Dict[str, List[Dict[str, Any]]]
    draft_answer: str
    final_answer: str
    retry_count: int


def _load_system_prompt() -> str:
    path = Path(config.SYSTEM_PROMPT_PATH)
    if not path.exists():
        return "You are a reliable copper-halide materials scientist assistant."
    return path.read_text(encoding="utf-8").strip()


def planner_node(state: AgentState) -> AgentState:
    llm = build_gemini_llm(temperature=0.1)
    system_prompt = _load_system_prompt()
    user_query = state.get("user_query", "Recommend copper halide candidates for broadband white light")

    prompt = (
        f"{system_prompt}\n\n"
        "Rewrite the user query into one short objective for KG retrieval.\n"
        "Return only one sentence.\n\n"
        f"User query: {user_query}"
    )
    objective = llm.invoke(prompt).content
    return {"objective": str(objective).strip(), "retry_count": state.get("retry_count", 0)}


def retriever_node(state: AgentState) -> AgentState:
    candidates = neo4j_tool.find_white_light_candidates(limit=5, min_fwhm=80, min_plqy=10)
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
    system_prompt = _load_system_prompt()

    payload = {
        "objective": state.get("objective"),
        "candidates": state.get("candidates", []),
        "evidence": state.get("evidence", {}),
    }

    prompt = (
        f"{system_prompt}\n\n"
        "You must rank the top 3 candidates for broadband white-light potential.\n"
        "For each candidate include: formula, why_selected, key_kg_evidence, confidence(0-1), next_experiment.\n"
        "Do not invent evidence outside payload.\n\n"
        f"Payload:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    draft = llm.invoke(prompt).content
    return {"draft_answer": str(draft).strip()}


def critic_node(state: AgentState) -> AgentState:
    candidates = state.get("candidates", [])
    evidence = state.get("evidence", {})
    draft = state.get("draft_answer", "")
    retry_count = state.get("retry_count", 0)

    has_candidates = len(candidates) > 0
    has_evidence = any(len(evidence.get(row["formula"], [])) > 0 for row in candidates)
    draft_ok = len(draft) > 30

    if has_candidates and has_evidence and draft_ok:
        return {"final_answer": draft}

    return {"retry_count": retry_count + 1}


def route_after_critic(state: AgentState) -> str:
    if state.get("final_answer"):
        return END
    if state.get("retry_count", 0) >= 1:
        return END
    return "retriever"


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
    graph.add_conditional_edges("critic", route_after_critic, {"retriever": "retriever", END: END})

    return graph.compile()


def run_agent(user_query: str) -> str:
    app = build_graph()
    result = app.invoke({"user_query": user_query})
    return result.get("final_answer") or result.get("draft_answer") or "No result generated."


def main() -> None:
    parser = argparse.ArgumentParser(description="Copper halide white-light LangGraph agent")
    parser.add_argument("query", nargs="?", default="Recommend broadband white-light copper halide candidates")
    args = parser.parse_args()

    try:
        output = run_agent(args.query)
        print(output)
    finally:
        neo4j_tool.close()


if __name__ == "__main__":
    main()
