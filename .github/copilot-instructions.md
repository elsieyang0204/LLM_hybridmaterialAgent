# Copper Halide AI Agent: Project Context & Status

## Project Objective
开发一个基于知识图谱 (Knowledge Graph, Neo4j) 和大语言模型 (Gemini 2.5 Flash) 的智能体 (Agent，基于 LangGraph)。
核心目标：针对“宽光谱白光铜卤化物 (Copper Halides for Broadband White-Light)”这一材料科学领域，提供已有材料的最佳候选推荐，以及预测尚未在 KG 中出现的新型候选材料，并给出可行的实验验证方案。

## Technology Stack
- **Agent Framework**: `langchain`, `langgraph`
- **LLM**: `langchain-google-genai` (Google Gemini 2.5 Flash / 3.0 Preview)
- **Database**: `neo4j` (Local graph database handling structured properties)
- **Material Science**: `pymatgen`, `mendeleev`
- **Observability**: LangSmith

## Project Structure & Deliverables (Current State)
1. **环境与配置**
   - `.env` & `config.py`: 集中管理 `NEO4J`、`GOOGLE_API_KEY`、`GEMINI_MODEL` 及 `LANGSMITH` 等敏感和全局配置。
   - `requirements.txt`: 核心依赖清单。

2. **核心逻辑 (Agent Core)**
   - `main_agent.py`: 实现了 LangGraph 的四节点工作流 MVP：
     - **Planner**: 解析用户目标。
     - **Retriever**: 从 Neo4j 获取 Top 候选材料及其属性证据。
     - **Reasoner**: 将图谱数据作为 Payload 送入 Gemini 进行排序和推理分析。
     - **Critic**: 检查幻觉，确保输出拥有证据支持。

3. **工具层 (Tools)**
   - `tools/neo4j_utils.py`: 封装了兼容实际图谱 Schema（宽属性表）的 Cypher 查询函数：
     - `find_white_light_candidates`：基于 FWHM（半峰宽）和 PLQY（量子产率）初筛。
     - `get_material_evidence`：提取支撑结论的可解释证据（对应关联文献）。
     - `find_similar_materials`：基于相同元素、家族（Family）和维度（0D/1D/3D）检索同类。
   - `tools/llm_utils.py`: Gemini 模型实例化模块，支持模型名标准化及多模型回退策略（如自动降级到可用版的 `gemini-2.5-flash`）。
   - `tools/chem_utils.py`: 基于 `pymatgen` 的化学处理工具，用于化合价平衡与配比检查。

4. **系统提示词 (Prompts)**
   - `prompts/system_p.txt`: 控制回答需遵循图谱内证据的专家系统设定。
   - `prompts/novel_candidate_prompt.txt`: 专门针对**KG 外新颖材料预测**的高级 Prompt 设计，结构化输出 JSON 候选，强制评估实验可行性和设计风险。

## Agent Workflow (LangGraph Architecture)
本项目的核心是一个基于状态图 (StateGraph) 的闭环反馈工作流，当前运行在 `main_agent.py` 中，具体运转逻辑如下：
1. **输入与意图解析 (Planner Node)**：
   接收用户的自然语言需求，结合 `system_p.txt` (专家角色)，提炼出单一的、可被后端明确查询的核心科学目标（例如：要求高热稳定性的宽光谱发光铜卤化物）。
2. **知识图谱检索 (Retriever Node)**：
   调用 `neo4j_utils.py` 连接 Graph DB：
   - 过滤出符合发光性能要求 (如 FWHM > 80, PLQY > 10%) 的 In-KG 实体现有材料。
   - 对初筛材料查询并打包它们所有的微观性质、CIE 坐标和对应文献证据 (Evidence)。
3. **推理与候选生成 (Reasoner Node)**：
   将目标和图谱返回的客观数据作为 payload 组装给 Gemini 进行逻辑推理：
   - **当下形态 (In-KG)**：根据用户要求对已知材料进行排序，并要求必须附带明确证据、置信度以及下一步实验建议。
   - **未来形态 (Out-of-KG)**：利用 `novel_candidate_prompt.txt` 中定义的零次/少次样本推荐替换逻辑（如原子等价位替代、掺杂），跳出现有 KG 组合出新的材料化学式，并返回严格的 JSON 评估规范代码。
4. **验证与纠错 (Critic Node)**：
   充当“幻觉”和“常识”终裁者。验证上一步输出：
   - 是否关联了足够支撑结论的 KG Evidence。
   - （后续加入）调用 `chem_utils.py` 自动化检查新建预测材料的电荷配平规则和离子半径是否容许。
   - 若出现幻觉或违背物理化学常识，则状态图会被路由**折返 (Loop back)**要求重试，直至符合条件后才输出给用户。

## Future Roadmap (Next Steps)
1. **JSON 结构化与新材料生成**：将 `novel_candidate_prompt.txt` 整合进入主 Agent 的另一路分支，允许图外 (Out-of-KG) 新预测节点运行并输出结构化的 Pydantic/JSON。
2. **严苛的化学检验**：使用 `chem_utils.py` 对新生成的 KG 外化学式进行离子半径合规与电荷中性校验。
3. **闭环评测集 (Evaluation)**：通过 LangSmith 搭建 10-20 个 benchmark questions，基于“命中率、证据引用正确性、无幻觉率”实现自动化打分。

## Copilot Guidelines for This Workspace
当你在该项目下提供协助代码时，请遵循以下准则：
1. **Database Queries**: 保持在 `tools/neo4j_utils.py` 中编写分离的查询层，并时刻注意图谱中 `HAS_PROPERTY` 指向的是一个包含多属性的宽节点而不是 Name/Value 键值对。
2. **LLM Calls**: 不要直接调用 Gemini，总是使用 `build_gemini_llm()`以利用其中的 API Key 和模型回退策略。
3. **Structure**: 确保新特征遵循当前的项目文件结构；图谱增强的逻辑放进 Retriever / Neo4j tool，生成校验放进 Critic / Chem tool。
