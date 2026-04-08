# Copper Halide AI Agent

基于知识图谱 Neo4j 与 Gemini 的铜卤化物智能体，面向宽光谱白光材料候选推荐与 KG 外新候选生成。

## 项目目标

本项目用于解决铜卤化物宽光谱白光材料的两个核心任务：

1. 从 Neo4j 知识图谱中检索已有材料候选，并给出可解释证据。
2. 基于图谱内证据与材料化学约束，生成尚未出现在 KG 中的新型候选材料，并通过电荷平衡校验。

## 技术栈

- Agent Framework: LangChain + LangGraph
- LLM: langchain-google-genai / Gemini 2.5 Flash
- Database: Neo4j
- Materials Science: pymatgen, mendeleev
- Observability: LangSmith
- Dependency Manager: uv

## 核心能力

- Planner: 解析用户目标与显式约束。
- ConstraintBuilder: 根据 `DYNAMIC_CONSTRAINTS` 决定使用 KG 动态阈值或固定回退阈值。
- Retriever: 从 Neo4j 中检索符合约束的已知材料与证据。
- Reasoner: 读取 `prompts/novel_candidate_prompt.txt`，生成 KG 外新候选。
- Critic: 对候选化学式做电荷平衡校验，不通过则回传 Reasoner 重新生成。
- JSON 提取器: 使用首个平衡花括号对象解析，避免贪婪正则误抓。

## 项目结构

```text
.
├── config.py
├── main_agent.py
├── evaluate_agent.py
├── test_gemini_connection.py
├── pyproject.toml
├── uv.lock
├── requirements.txt
├── prompts/
│   ├── system_p.txt
│   └── novel_candidate_prompt.txt
├── tools/
│   ├── chem_utils.py
│   ├── llm_utils.py
│   └── neo4j_utils.py
└── .github/
    ├── copilot-instructions.md
    ├── copilot_instructions.md
    └── skills/
        └── kg_matetrials/
            └── SKILL.md
```

## 环境要求

- Python 3.11
- uv
- Neo4j 本地或远程实例
- Google Gemini API Key

## 配置文件

在项目根目录创建 `.env`，至少包含：

```env
NEO4J_URI=bolt://localhost:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_password
GOOGLE_API_KEY=your_google_api_key
GEMINI_MODEL=gemini-2.5-flash
DYNAMIC_CONSTRAINTS=true
LANGCHAIN_TRACING_V2=false
```

## uv 启动教程

### 1. 安装锁定依赖

```powershell
uv sync --frozen
```

### 2. 启动主程序

推荐直接运行，不依赖手动激活虚拟环境：

```powershell
uv run python main_agent.py "Recommend broadband white-light copper halide candidates"
```

### 3. 可选：激活虚拟环境后运行

```powershell
.\.venv\Scripts\Activate.ps1
python main_agent.py "Recommend broadband white-light copper halide candidates"
```

### 4. 连通性检查

```powershell
uv run python test_gemini_connection.py
```

### 5. 评测脚本

```powershell
uv run python evaluate_agent.py --first-try-runs 5 --consistency-runs 3
```

## 常用 uv 维护命令

- 新增依赖：`uv add <package>`
- 更新锁文件：`uv lock --upgrade`
- 导出兼容 requirements：`uv export --format requirements-txt -o requirements.txt`

## 运行说明

- `main_agent.py` 会输出最终 JSON 结果，并尝试写入 `generated_candidates.json`。
- `evaluate_agent.py` 用于 first-try pass rate 和一致性评测。
- `test_gemini_connection.py` 用于检查 LangSmith 状态和 Gemini 连通性。

## Git 忽略说明

项目中以下内容默认不入库：

- `.env`
- `.venv/`
- `output_in_KG/`
- `generated_*.json`
- `chem_intercept_log.txt`
- `graph TD.txt`
- `report_evaluation_draft.md`

## 设计约束

- 所有 Gemini 调用统一通过 `build_gemini_llm()`。
- Neo4j 查询统一放在 `tools/neo4j_utils.py`。
- 化学电荷校验统一放在 `tools/chem_utils.py`。
- `DYNAMIC_CONSTRAINTS=true` 时优先使用 KG 分位数动态阈值；关闭时回退到固定阈值。

## 备注

如果你是第一次在本机运行这个项目，建议先确认：

1. `.env` 已正确配置
2. Neo4j 可连接
3. `uv sync --frozen` 成功执行
4. `uv run python test_gemini_connection.py` 可正常返回
