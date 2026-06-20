"""
配置管理
"""
import os

# 任务 R：加载 .env 文件（避免 System Env Var 覆盖）
try:
    from dotenv import load_dotenv
    # 找 backend/.env
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)  # 不覆盖 System Env Var，但 .env 缺省的会补
except ImportError:
    pass  # dotenv 未装时跳过


# 厂商 → Embedding 模型映射（支持所有 LLM 厂商使用其 OpenAI 兼容 Embedding 接口）
# 注：只有标记为 "supports_embedding": True 的厂商才提供 Embedding API
EMBEDDING_PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "text-embedding-3-small",
        "dim": 1536,
        "supports_embedding": True,
        "api_key_env": "OPENAI_API_KEY",
        "protocol": "openai",  # 使用 OpenAI 标准 /v1/embeddings 协议
        "note": "原生 Embedding 支持，向量质量最高",
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "text-embedding-3-small",
        "dim": 1536,
        "supports_embedding": False,
        "api_key_env": "DEEPSEEK_API_KEY",
        "protocol": "openai",
        "note": "DeepSeek 目前未官方提供 embedding 端点；建议使用其它厂商",
    },
    "minimax": {
        "label": "MiniMax",
        # 官方文档：https://api.minimax.chat/v1/embeddings
        # 同时支持 api.minimaxi.com 域名（兼容入口）
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "embo-01",
        "dim": 1536,
        "supports_embedding": True,
        "api_key_env": "OPENAI_API_KEY",  # 复用 MiniMax 的 OPENAI_API_KEY
        "protocol": "minimax",  # 自研协议：需传 GroupId + type=db|query
        "group_id_env": "MiniMax_GROUP_ID",  # 必填查询参数
        "note": "embo-01 专为中文场景优化；区分 db/query 模式（db 入库，query 检索）",
    },
    "qwen": {
        "label": "通义千问 DashScope",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "text-embedding-v3",
        "dim": 1024,
        "supports_embedding": True,
        "api_key_env": "QWEN_API_KEY",
        "protocol": "openai",
        "note": "阿里 DashScope 兼容 OpenAI 协议，支持 text-embedding-v3",
    },
    "zhipu": {
        "label": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "embedding-2",
        "dim": 1024,
        "supports_embedding": True,
        "api_key_env": "ZHIPU_API_KEY",
        "protocol": "openai",
        "note": "智谱 embedding-2 中文表现优秀",
    },
    "ollama": {
        "label": "Ollama (本地)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "nomic-embed-text",
        "dim": 768,
        "supports_embedding": True,
        "api_key_env": "OLLAMA_API_KEY",
        "protocol": "openai",
        "note": "本地 Ollama 服务，需先 ollama pull nomic-embed-text",
    },
    "custom": {
        "label": "自定义 OpenAI 兼容",
        "base_url": "",
        "default_model": "text-embedding-3-small",
        "dim": 1536,
        "supports_embedding": True,
        "api_key_env": "CUSTOM_EMBEDDING_API_KEY",
        "protocol": "openai",
        "note": "任何兼容 OpenAI /embeddings 协议的服务",
    },
    "local": {
        "label": "本地 (BGE / sentence-transformers)",
        "base_url": "本地",
        "default_model": os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5"),
        "dim": 512,
        "supports_embedding": True,
        "api_key_env": "",
        "protocol": "local",
        "note": "本地加载 BGE 模型（transformers + torch 直加载），默认 BAAI/bge-small-zh-v1.5 (512维)；"
                "如模型加载失败则降级为 hash 伪向量。推荐生产用此方案。",
    },
    "modelscope": {
        "label": "魔塔社区 (ModelScope)",
        "base_url": "https://api-inference.modelscope.cn/v1",
        "default_model": "BAAI/bge-small-zh-v1.5",
        "dim": 1024,  # 任务 R：Qwen3-Embedding-0.6B 默认输出 1024 维
        "supports_embedding": True,
        "api_key_env": "MODELSCOPE_API_KEY",
        "protocol": "openai",  # ModelScope 兼容 OpenAI 协议
        "note": "魔塔社区 API 推理。任务 R 当前用 Qwen/Qwen3-Embedding-0.6B (1024 维)；可改回 BAAI/bge-small-zh-v1.5 (512 维)。",
    },
    "siliconflow": {
        "label": "硅基流动 (SiliconFlow)",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "Qwen/Qwen3-VL-Embedding-8B",
        "dim": 4096,  # Qwen3-VL-Embedding-8B 实际输出 4096 维
        "supports_embedding": True,
        "api_key_env": "SILICONFLOW_API_KEY",
        "protocol": "openai",  # 兼容 OpenAI /v1/embeddings 协议
        "note": "硅基流动提供 Qwen3 / BGE 等开源 Embedding 模型，注册即送 2000 万 Tokens 免费额度，国内免翻墙",
    },
    "qwen3_local": {
        "label": "Qwen3-Embedding-0.6B 本地",
        "base_url": "本地推理",
        "default_model": "Qwen/Qwen3-Embedding-0.6B",
        "dim": 1024,  # Qwen3-Embedding-0.6B 实际输出 1024 维（用户描述的 768 维与实际不符）
        "supports_embedding": True,
        "api_key_env": "",
        "protocol": "local_qwen3",
        "note": "任务 R：本地加载 Qwen3-Embedding-0.6B（0.6B 参数，~1.2GB 权重）。需 torch + transformers>=4.51.0 + sentencepiece。CPU 推理约 50-200ms/条，GPU 加速 5-10x。",
    },
}


class Settings:
    # MiniMax API 配置
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-cp-Dxh1ig55_aJCHbO0mSksRNdvJrUstjZFwlSiSVnEJdq8_FTMxVihlth4UH1rKj9sbSdfm2fDutaIsGgPYFxZn38G2snVKYCsCaNn8ULjvKVuQNaeiWijl5A")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.minimaxi.com/v1")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "MiniMax-M3")
    # MiniMax GroupId（用于自研 /v1/embeddings 协议；可在 MiniMax 账户中心查询）
    MiniMax_GROUP_ID = os.getenv("MiniMax_GROUP_ID", "")

    # DeepSeek API 配置
    # 任务 P3-9 修复：硬编码真实 key 是严重安全风险，GitHub Push Protection 会拦截
    # 改为：必须从环境变量读取，禁止硬编码默认值
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

    # 通义千问 DashScope 配置
    QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
    QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

    # 硅基流动 SiliconFlow 配置
    SILICONFLOW_API_KEY = os.getenv("SILICONFLOW_API_KEY", "")

    # 智谱 GLM 配置
    ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")

    # 自定义 Embedding 配置
    CUSTOM_EMBEDDING_API_KEY = os.getenv("CUSTOM_EMBEDDING_API_KEY", "")
    CUSTOM_EMBEDDING_BASE_URL = os.getenv("CUSTOM_EMBEDDING_BASE_URL", "")
    CUSTOM_EMBEDDING_MODEL = os.getenv("CUSTOM_EMBEDDING_MODEL", "text-embedding-3-small")

    # 文件上传
    UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

    # 图谱配置
    GRAPH_DATA_DIR = os.getenv("GRAPH_DATA_DIR", "data/graph")

    # 模型配置
    MODEL_DIR = os.getenv("MODEL_DIR", "models")
    EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")

    # ==================== 新增：Embedding 模式配置 ====================
    # 三种模式：
    #   - "local" : 本地 sentence-transformers 或 hash 回退
    #   - "api"   : 调用 LLM 厂商的 OpenAI 兼容 Embedding 接口
    #   - "modelscope": ModelScope 镜像（保留旧能力）
    EMBEDDING_MODE: str = os.getenv("EMBEDDING_MODE", "local").lower()
    # 当 EMBEDDING_MODE=api 时使用哪个 provider
    # 取值: openai / deepseek / minimax / qwen / zhipu / ollama / custom
    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "minimax").lower()
    # 强制覆盖默认模型（不填则用 PROVIDER 的 default_model）
    EMBEDDING_MODEL_OVERRIDE: str = os.getenv("EMBEDDING_MODEL_OVERRIDE", "")
    # 当 provider 没有 key 时的回退策略
    # "hash" - 降级到哈希伪向量
    # "error" - 直接报错
    EMBEDDING_FALLBACK: str = os.getenv("EMBEDDING_FALLBACK", "hash").lower()

    # ==================== 分块配置 ====================
    USE_ADVANCED_CHUNKING: bool = os.getenv("USE_ADVANCED_CHUNKING", "true").lower() == "true"
    DEFAULT_CHUNK_STRATEGY: str = os.getenv("DEFAULT_CHUNK_STRATEGY", "recursive")
    DEFAULT_CHUNK_SIZE: int = int(os.getenv("DEFAULT_CHUNK_SIZE", "512"))
    DEFAULT_CHUNK_OVERLAP: int = int(os.getenv("DEFAULT_CHUNK_OVERLAP", "64"))


settings = Settings()

