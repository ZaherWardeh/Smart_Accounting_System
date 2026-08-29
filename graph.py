"""LangGraph StateGraph replacing the old linear analyze_with_ai() pipeline.

classify_intent -> route -> one of {handle_ambiguous, handle_out_of_scope,
handle_greeting, agent_loop} -> END.

agent_loop replaces the old inquiry_proc()'s two exec() calls + synthesis
prompt with a single node that binds the three domain tools (tools.py) and
drives a bounded multi-turn tool-calling loop against Gemini.
"""

import json
import re
from typing import Optional, TypedDict

from google.genai import types
from fastapi import HTTPException, status
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

import analysis
from analysis import (
    intent_analysis,
    prompt_Ambiguity_Response,
    prompt_Out_of_Scope_Response,
    welcoming_proc,
)
from tools import TOOL_DECLARATIONS, TOOL_FUNCTIONS

MAX_TOOL_ROUNDS = 6

INTENT_TITLES = {
    "Accounting Inquiry": "محاسب ذكي",
    "Financial Analysis": "محلل مالي ذكي",
}
DEFAULT_TITLE = "مساعد بيانات محاسبية ذكي"


class AgentState(TypedDict, total=False):
    question: str
    intent: Optional[str]
    confidence: Optional[str]
    reason: Optional[str]
    messages: list
    answer: Optional[str]
    error: Optional[str]


# ---------------------------------------------------------------------------
# classify_intent / route
# ---------------------------------------------------------------------------

def classify_intent(state: AgentState) -> AgentState:
    raw = intent_analysis(state["question"])
    cleaned = re.sub(r"```json|```", "", raw).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        state["intent"] = None
        state["confidence"] = "low"
        state["reason"] = "Could not parse intent classification response"
        return state

    state["intent"] = parsed.get("intent")
    state["confidence"] = parsed.get("confidence")
    state["reason"] = parsed.get("reason")
    return state


def route(state: AgentState) -> str:
    if state.get("confidence") == "low":
        return "handle_ambiguous"
    intent = state.get("intent")
    if intent == "Out of Scope":
        return "handle_out_of_scope"
    if intent == "Greeting":
        return "handle_greeting"
    if intent in ("Accounting Inquiry", "Financial Analysis", "Data Request"):
        return "agent_loop"
    return "handle_ambiguous"


# ---------------------------------------------------------------------------
# simple single-shot nodes
# ---------------------------------------------------------------------------

def handle_ambiguous(state: AgentState) -> AgentState:
    state["answer"] = prompt_Ambiguity_Response(state["question"])
    return state


def handle_out_of_scope(state: AgentState) -> AgentState:
    state["answer"] = prompt_Out_of_Scope_Response(state["question"])
    return state


def handle_greeting(state: AgentState) -> AgentState:
    state["answer"] = welcoming_proc(state["question"])
    return state


# ---------------------------------------------------------------------------
# agent_loop: tool-calling node
# ---------------------------------------------------------------------------

def _build_agent_system_prompt(intent: str, question: str) -> str:
    title = INTENT_TITLES.get(intent, DEFAULT_TITLE)
    return f"""
اسمك "ريما" وأنت {title} داخل برنامج محاسبة.

قاعدة اللغة:
يجب أن تجيب دائماً باللغة نفسها التي استخدمها المستخدم في سؤاله، سواء كانت عربية، إنكليزية، فرنسية أو أي لغة أخرى — بدون أي استثناء. يمنع عليك الرد باللغة العربية إذا كان سؤال المستخدم بلغة مختلفة.

لديك ثلاث أدوات للوصول إلى البيانات المحاسبية:
- get_chart_of_accounts: لجلب كل الحسابات، أنواعها (رئيسي/فرعي) ومعرفاتها.
- get_account_transactions: لجلب حركة حساب معين ضمن مدى تاريخي.
- get_account_balance: لجلب رصيد حساب أو أكثر (مجموع + تفصيل لكل حساب).

قواعد استخدام الأدوات:
1. لا تخمّن معرف أي حساب أبداً؛ استخدم get_chart_of_accounts أولاً للتأكد من الاسم والمعرف قبل استدعاء الأداتين الأخريين.
2. إذا تطابق اسم الحساب مع أكثر من حساب واحد، لا تختر عشوائياً — اذكر للمستخدم كل الخيارات (الاسم، الحساب الأب، نوع الإغلاق) واطلب منه تحديد المقصود بسؤال أدق.
3. لمفاهيم شاملة مثل "السيولة" التي تضم عدة حسابات (صندوق، بنك...)، حدد كل الحسابات ذات الصلة من دليل الحسابات ثم استدعِ get_account_balance بقائمة معرفاتها دفعة واحدة، واذكر في إجابتك أي الحسابات تم جمعها وليس فقط الرقم النهائي.
4. الحسابات ذات closeIn="Balance Sheet" رصيدها تراكمي حتى تاريخ معين (as_of_date). الحسابات ذات closeIn="P&L" أو "Trading" لا تعني شيئاً إلا ضمن فترة، لذا استخدم date_from/date_to معها.
5. الأدوات لا تحدد لك إشارة الرصيد (مدين/دائن، لك/عليك) — هذا الحكم متروك لك كمحاسبة خبيرة بالاعتماد على اسم الحساب ومعرفتك المحاسبية.
6. استمر باستدعاء الأدوات حتى تجمع كل المعلومات اللازمة، ثم أجب بنص واضح نهائي (وليس استدعاء أداة إضافي) عندما تكون جاهزاً.

سؤال المستخدم: '{question}'

ابدأ الآن.
"""


def _run_tool(db: Session, name: str, args: dict) -> dict:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return func(db, **args)
    except Exception as e:
        return {"error": str(e)}


def _generate_with_tools(contents: list, tool: types.Tool):
    if not analysis.client:
        raise HTTPException(
            status_code=status.HTTP_417_EXPECTATION_FAILED,
            detail="Google client could not attached, check your API key",
        )
    try:
        return analysis.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(tools=[tool]),
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google client could not manage your request:'{str(e)}'",
        )


def agent_loop(state: AgentState, db: Session) -> AgentState:
    question = state["question"]
    intent = state.get("intent") or "Data Request"

    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=d["name"], description=d["description"], parameters=d["parameters"]
            )
            for d in TOOL_DECLARATIONS
        ]
    )

    contents = [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=_build_agent_system_prompt(intent, question))],
        )
    ]

    final_text = None
    response = None
    for _ in range(MAX_TOOL_ROUNDS):
        response = _generate_with_tools(contents, tool)
        candidate = response.candidates[0]
        function_calls = [p.function_call for p in candidate.content.parts if p.function_call]

        if not function_calls:
            final_text = response.text
            break

        contents.append(candidate.content)
        response_parts = [
            types.Part.from_function_response(
                name=fc.name, response={"result": _run_tool(db, fc.name, dict(fc.args or {}))}
            )
            for fc in function_calls
        ]
        contents.append(types.Content(role="tool", parts=response_parts))

    if final_text is None:
        final_text = response.text if response is not None else None

    state["messages"] = contents
    state["answer"] = final_text or prompt_Ambiguity_Response(question)
    return state


# ---------------------------------------------------------------------------
# graph assembly
# ---------------------------------------------------------------------------

def build_graph(db: Session):
    workflow = StateGraph(AgentState)
    workflow.add_node("classify_intent", classify_intent)
    workflow.add_node("handle_ambiguous", handle_ambiguous)
    workflow.add_node("handle_out_of_scope", handle_out_of_scope)
    workflow.add_node("handle_greeting", handle_greeting)
    workflow.add_node("agent_loop", lambda state: agent_loop(state, db))

    workflow.set_entry_point("classify_intent")
    workflow.add_conditional_edges(
        "classify_intent",
        route,
        {
            "handle_ambiguous": "handle_ambiguous",
            "handle_out_of_scope": "handle_out_of_scope",
            "handle_greeting": "handle_greeting",
            "agent_loop": "agent_loop",
        },
    )
    workflow.add_edge("handle_ambiguous", END)
    workflow.add_edge("handle_out_of_scope", END)
    workflow.add_edge("handle_greeting", END)
    workflow.add_edge("agent_loop", END)

    return workflow.compile()


def run_agent(db: Session, question: str) -> str:
    graph = build_graph(db)
    result = graph.invoke({"question": question, "messages": []})
    return result.get("answer")
