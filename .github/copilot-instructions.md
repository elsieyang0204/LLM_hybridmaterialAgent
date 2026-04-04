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
   - `.env` & `config.py`: 集中管理 `NEO4J`、`GOOGLE_API_KEY`、`GEMINI_MODEL` 及 `LANGSMITH` 等敏感和全局配置。（注意：.env文件及所有本地保存的新材料JSON结果等会被`.gitignore`隔离，从而避免隐私和数据库密码泄露）。
   - `requirements.txt`: 核心依赖清单。

2. **核心逻辑 (Agent Core)**
   - `main_agent.py`: 实现了基于 LangGraph 的四节点闭环强化工作流：
     - **Planner**: 解析用户目标。**不再使用硬编码阈值**，而是动态解析用户 query 获取指定的最小 `FWHM` 和 `PLQY` 指标。
     - **Retriever**: 根据 Planner 动态生成的指标和提取任务从 Neo4j 数据库中获取 Top 候选材料及其属性证据。
     - **Reasoner**: 获取图谱里的已知材料作为参考基准，然后加载 `novel_candidate_prompt.txt` 作为系统提示词，强制模型跳出图谱生成全新材料（Out-of-KG），并固定返回强结构的 JSON Schema 输出。
     - **Critic**: 解析生成的 JSON 并校验**电荷平衡 (Charge Balance)**。使用 `chem_utils.py` 自动化审查；若配平错误，会自动将报错信息（Feedback）折返 (Loopback) 回 `Reasoner` 让大语言模型基于错误进行修正。

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
   接收用户的自然语言需求，解析出具体的客观性能阈值（如 min_fwhm, min_plqy）以及搜索目标，以 JSON 传递给 Retriever。
2. **知识图谱检索 (Retriever Node)**：
   动态获取从 Planner 传来的指标，调用 `neo4j_utils.py` 连接 Graph DB，过滤出符合发光性能要求的 In-KG 现有材料，收集证据数据。
3. **推理与候选生成 (Reasoner Node)**：
   将目标和检索证据数据作为 payload，**强制加载 `novel_candidate_prompt.txt`** 进行严格推理约束：要求大语言模型必须生成出非已知 KG 的**全新候选材料 (Novel Candidates)**，并通过设定好的 JSON 结构输出设计意图、预期趋势等信息。
4. **验证与纠错 (Critic Node)**：
   利用 `chem_utils.py` 自动化检测每一个预测得到的新公式是否遵循**电荷平衡法则**。如果检测到未通过化学规则的项或者非预期的 JSON 输出，Critic 节点将不再简单报错失败返回 Retriever，而是携带 `feedback` (具体的电荷错误) 路由**折返 (Loop back) 至 Reasoner Node**，让模型参考出错原因重新生成合理的化学式。成功通过测试后输出最终 JSON。

## Future Roadmap (Next Steps)
1. **闭环评测集 (Evaluation)**：通过 LangSmith 搭建 10-20 个 benchmark questions，基于“命中率、证据引用正确性、无幻觉率”实现自动化打分。
2. **多模态与进阶验证**：集成更深度的物理性质预测。

## Copilot Guidelines for This Workspace
当你在该项目下提供协助代码时，请遵循以下准则：
1. **Database Queries**: 保持在 `tools/neo4j_utils.py` 中编写分离的查询层，并时刻注意图谱中 `HAS_PROPERTY` 指向的是一个包含多属性的宽节点而不是 Name/Value 键值对。
2. **LLM Calls**: 不要直接调用 Gemini，总是使用 `build_gemini_llm()`以利用其中的 API Key 和模型回退策略。
3. **Structure**: 确保新特征遵循当前的项目文件结构；图谱增强的逻辑放进 Retriever / Neo4j tool，生成校验放进 Critic / Chem tool。
