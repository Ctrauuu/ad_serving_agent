from functools import lru_cache

from langchain_core.exceptions import OutputParserException
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.schemas import GoalParseResult


_parser=PydanticOutputParser(pydantic_object=GoalParseResult)

_SYSTEM_PROMPT = f"""
你负责把自然语言广告投放目标转换为结构化 JSON。

规则：
1. 只能提取用户明确提供的信息，禁止猜测或补造。
2. 信息完整时，填写 structured_goal，missing_fields 返回空数组。
3. 信息不完整时，structured_goal 返回 null，missing_fields 返回缺失字段。
4. missing_fields 只能使用：
   product、audience、budget、cycle、conversion_goal、channels、risk。
5. 必须输出合法 JSON。

{_parser.get_format_instructions()}
"""

@lru_cache
def get_goal_llm() -> ChatOpenAI:
    """创建目标解析模型客户端。

    Returns:
        配置完成的模型客户端。
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.dashscope_model,
        api_key=settings.dashscope_api_key.get_secret_value(), # type: ignore
        base_url=settings.dashscope_base_url,
        temperature=0,
        model_kwargs={
            "response_format": {"type": "json_object"},
        },
        extra_body={
            "enable_thinking": False,
        },
    )

async def parse_goal_text(
    goal_text: str,
) -> GoalParseResult:
    """解析并校验投放目标。

    Args:
        goal_text: 自然语言目标。

    Returns:
        返回类型为 GoalParseResult 的执行结果。
    """
    response = await get_goal_llm().ainvoke(
        [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(
                content=f"投放目标：{goal_text}"
            ),
        ]
    )

    if not isinstance(response.content, str):
        raise ValueError("模型未返回文本内容")

    try:
        result = _parser.parse(response.content)
    except OutputParserException as exc:
        raise ValueError(
            "模型返回内容不符合结构化目标格式"
        ) from exc

    if result.missing_fields:
        return GoalParseResult(
            missing_fields=result.missing_fields
        )

    if result.structured_goal is None:
        raise ValueError(
            "模型未返回结构化目标或缺失字段"
        )

    return result
