---
name: kg-material
description: "Use when: copper halide candidate generation, Neo4j retrieval, charge-balance validation, LangGraph planner/retriever/reasoner/critic workflow."
---

# KG Material Skill

## When to use
- Need material recommendation from Neo4j evidence
- Need out-of-KG novel candidate generation
- Need charge-balance check and correction loop

## Required project rules
- Always use build_gemini_llm() for LLM calls
- Keep Cypher in tools/neo4j_utils.py
- Put chemistry validation in tools/chem_utils.py

## Workflow
1. Parse user thresholds (FWHM, PLQY)
2. Retrieve in-KG candidates and evidence
3. Generate out-of-KG candidates with structured JSON
4. Run charge-balance checks; if failed, regenerate with feedback

## Output contract
- Return JSON with: formula, design_rationale, expected_trend, feasibility, risk
- Include evidence references from KG when applicable