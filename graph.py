"""LangGraph agent for /reports/ask_ai.

A single node ("agent_loop") replaces the earlier classify_intent -> route ->
{handle_ambiguous, handle_out_of_scope, handle_greeting, agent_loop} pipeline.
Persona, scope restriction, greeting/ambiguity handling and tool use are all
prompt-engineered into one system_instruction rather than a separate
classification call + hard-coded routing. Per-conversation history is kept
server-side (in-memory, keyed by conversation_id supplied by the caller) so
the model has real multi-turn memory instead of answering each question in
isolation.
"""

import os
import threading
from collections import OrderedDict
from typing import Optional, TypedDict

from dotenv import load_dotenv
from google import genai
from google.genai import types
from fastapi import HTTPException, status
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from tools import TOOL_DECLARATIONS, TOOL_FUNCTIONS

load_dotenv()

client = None
try:
    API_Key = os.getenv("API_KEY")
    client = genai.Client(api_key=API_Key)
    print("Gemini client was created successfully")
except Exception as e:
    print(f"Error creating Gemini client: {e}")


def is_llm_connected() -> bool:
    """True once the Gemini client initialized (a present, well-formed
    API_KEY). Doesn't make a live call, so it can't tell a bad/expired key
    from a good one - just "unconfigured" vs "configured"."""
    return client is not None


MAX_TOOL_ROUNDS = 6

# Bounds on the in-memory conversation store: the oldest conversation is
# evicted once more than MAX_TRACKED_CONVERSATIONS are held, and any single
# conversation keeps only its most recent MAX_HISTORY_ENTRIES turns.
MAX_TRACKED_CONVERSATIONS = 500
MAX_HISTORY_ENTRIES = 40

FALLBACK_ANSWER = "عذراً، لم أتمكن من الوصول إلى إجابة واضحة، ممكن تعيد صياغة سؤالك بشكل مختلف؟"

# system_instruction is resent with every API call (Gemini's generate_content
# is stateless per request), but it is authored once here and never
# duplicated into the growing conversation history — the per-turn `contents`
# list only ever carries the actual question/answer/tool exchanges.
SYSTEM_PROMPT_CORE = """
اسمك "ريما" وأنت محاسبة ذكية خبيرة داخل برنامج محاسبة.

قاعدة اللغة:
يجب أن تجيبي دائماً باللغة نفسها التي استخدمها المستخدم في سؤاله، سواء كانت عربية، إنكليزية، فرنسية أو أي لغة أخرى — بدون أي استثناء. يمنع عليك الرد باللغة العربية إذا كان سؤال المستخدم بلغة مختلفة.

نطاق عملك:
أنتِ مختصة فقط بالأسئلة المحاسبية والمالية المتعلقة ببيانات هذا البرنامج (دليل الحسابات، الحركات، الأرصدة، التحليل المالي).
- إذا كانت رسالة المستخدم تحية أو كلام اجتماعي (شكراً، تمام، أهلاً...) بلا طلب فعلي، ردّي بشكل طبيعي ولطيف دون اعتذار.
- إذا كان طلباً أو سؤالاً فعلياً لا علاقة له بالمحاسبة أو المالية، اعتذري بلباقة ووضحي أنك مختصة فقط بالأسئلة المحاسبية، دون تنفيذ أي جزء من الطلب غير المحاسبي.
- لا تستخدمي أي أداة إلا للأسئلة المحاسبية/المالية الفعلية.

عند الغموض:
إذا كان سؤال المستخدم غامضاً أو غير كافٍ لتحديد ما يريده بدقة، لا تخمّني ولا تستخدمي أي أداة — اطلبي منه بلطف أن يوضح أو يعيد صياغة سؤاله أولاً.

الذاكرة:
لديك تاريخ المحادثة كاملاً كسياق سابق — استخدميه لفهم الإشارات المرجعية (مثل "الأول" أو "نفس الحساب يلي حكينا عنه") بدل ما تسألي المستخدم من جديد لو كانت المعلومة موجودة بالتاريخ.

لديك ثلاث أدوات للوصول إلى البيانات المحاسبية:
- get_chart_of_accounts: لجلب كل الحسابات، أنواعها (رئيسي/فرعي) ومعرفاتها.
- get_account_transactions: لجلب حركة حساب معين ضمن مدى تاريخي.
- get_account_balance: لجلب رصيد حساب أو أكثر (مجموع + تفصيل لكل حساب).

قواعد استخدام الأدوات:
1. لا تخمّني معرف أي حساب أبداً؛ استخدمي get_chart_of_accounts أولاً للتأكد من الاسم والمعرف قبل استدعاء الأداتين الأخريين (إلا إذا كان معرف الحساب معروفاً مسبقاً من سياق المحادثة).
2. إذا تطابق اسم الحساب مع أكثر من حساب واحد، لا تختاري عشوائياً — اذكري للمستخدم كل الخيارات (الاسم، الحساب الأب، نوع الإغلاق) واطلبي منه تحديد المقصود.
3. لمفاهيم شاملة مثل "السيولة" التي تضم عدة حسابات (صندوق، بنك...)، حددي كل الحسابات ذات الصلة من دليل الحسابات ثم استدعِ get_account_balance بقائمة معرفاتها دفعة واحدة، واذكري بإجابتك أي الحسابات تم جمعها وليس فقط الرقم النهائي.
4. الحسابات ذات closeIn="Balance Sheet" رصيدها تراكمي حتى تاريخ معين (as_of_date). الحسابات ذات closeIn="P&L" أو "Trading" لا تعني شيئاً إلا ضمن فترة، لذا استخدمي date_from/date_to معها.
5. الأدوات لا تحدد لك إشارة الرصيد (مدين/دائن) — هذا الحكم متروك لك كمحاسبة خبيرة بالاعتماد على اسم الحساب ومعرفتك المحاسبية.
6. استمري باستدعاء الأدوات حتى تجمعي كل المعلومات اللازمة، ثم أجيبي بنص واضح نهائي (وليس استدعاء أداة إضافي) عندما تكوني جاهزة.
"""

SYSTEM_PROMPT_FIRST_TURN_INTRO = """
ملاحظة: هذه أول رسالة من المستخدم بهذه المحادثة. ابدئي إجابتك بجملة قصيرة تعرّفين فيها عن نفسك (اسمك ريما ومهمتك)، ثم أكملي بالإجابة عن سؤاله. لا داعي لتكرار هذا التعريف في أي رسالة لاحقة بنفس المحادثة.
"""


class AgentState(TypedDict, total=False):
    conversation_id: str
    question: str
    db: Session
    answer: Optional[str]


# ---------------------------------------------------------------------------
# per-conversation history store (in-memory, process-local, bounded)
# ---------------------------------------------------------------------------

_CONVERSATIONS: "OrderedDict[str, list]" = OrderedDict()
_CONVERSATION_LOCKS: dict[str, threading.Lock] = {}
_STORE_LOCK = threading.Lock()


def _get_conversation_lock(conversation_id: str) -> threading.Lock:
    """One lock per conversation_id, so concurrent requests on the SAME
    conversation serialize (no lost-update on the shared history) while
    different conversations stay fully concurrent."""
    with _STORE_LOCK:
        return _CONVERSATION_LOCKS.setdefault(conversation_id, threading.Lock())


def _get_history(conversation_id: str) -> list:
    with _STORE_LOCK:
        return list(_CONVERSATIONS.get(conversation_id, []))


def _save_history(conversation_id: str, contents: list) -> None:
    with _STORE_LOCK:
        _CONVERSATIONS[conversation_id] = contents[-MAX_HISTORY_ENTRIES:]
        _CONVERSATIONS.move_to_end(conversation_id)
        while len(_CONVERSATIONS) > MAX_TRACKED_CONVERSATIONS:
            evicted_id, _ = _CONVERSATIONS.popitem(last=False)
            _CONVERSATION_LOCKS.pop(evicted_id, None)


def clear_conversation(conversation_id: str) -> None:
    with _STORE_LOCK:
        _CONVERSATIONS.pop(conversation_id, None)
        _CONVERSATION_LOCKS.pop(conversation_id, None)


# ---------------------------------------------------------------------------
# agent_loop: single node, tool-calling + persona + scope in one prompt
# ---------------------------------------------------------------------------

def _run_tool(db: Session, name: str, args: dict) -> dict:
    func = TOOL_FUNCTIONS.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return func(db, **args)
    except Exception as e:
        return {"error": str(e)}


def _generate_with_tools(contents: list, config: types.GenerateContentConfig):
    if not client:
        raise HTTPException(
            status_code=status.HTTP_417_EXPECTATION_FAILED,
            detail="Google client could not attached, check your API key",
        )
    try:
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=config,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google client could not manage your request:'{str(e)}'",
        )


def _run_tool_calling_rounds(contents: list, config: types.GenerateContentConfig, db: Session):
    """Runs the bounded call -> execute-tool -> feed-result-back loop.
    Returns (final_text, contents). On success, contents ends with the
    model's final plain-text turn. If MAX_TOOL_ROUNDS is exhausted without a
    final answer, final_text is None — the caller decides what to persist."""
    final_text = None
    for _ in range(MAX_TOOL_ROUNDS):
        response = _generate_with_tools(contents, config)
        candidate = response.candidates[0]
        function_calls = [p.function_call for p in candidate.content.parts if p.function_call]

        contents.append(candidate.content)

        if not function_calls:
            final_text = response.text
            break

        response_parts = [
            types.Part.from_function_response(
                name=fc.name, response={"result": _run_tool(db, fc.name, dict(fc.args or {}))}
            )
            for fc in function_calls
        ]
        # Gemini's Content.role only accepts "user" or "model" - function
        # responses go back as a "user" turn, there is no "tool" role.
        contents.append(types.Content(role="user", parts=response_parts))

    return final_text, contents


def agent_loop(state: AgentState) -> AgentState:
    conversation_id = state["conversation_id"]
    question = state["question"]
    db = state["db"]

    with _get_conversation_lock(conversation_id):
        history = _get_history(conversation_id)
        is_first_turn = len(history) == 0

        system_instruction = SYSTEM_PROMPT_CORE + (SYSTEM_PROMPT_FIRST_TURN_INTRO if is_first_turn else "")

        tool = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name=d["name"], description=d["description"], parameters=d["parameters"]
                )
                for d in TOOL_DECLARATIONS
            ]
        )
        config = types.GenerateContentConfig(system_instruction=system_instruction, tools=[tool])

        contents = history + [types.Content(role="user", parts=[types.Part.from_text(text=question)])]

        final_text, contents = _run_tool_calling_rounds(contents, config, db)

        if final_text is None:
            # the round cap was hit mid tool-call exchange - don't persist a
            # dangling, never-answered turn into memory; this question simply
            # never happened as far as later turns are concerned.
            final_text = FALLBACK_ANSWER
            contents = history

        _save_history(conversation_id, contents)

    state["answer"] = final_text
    return state


# ---------------------------------------------------------------------------
# graph assembly - built once at import time, the structure is static
# ---------------------------------------------------------------------------

def _build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent_loop", agent_loop)
    workflow.set_entry_point("agent_loop")
    workflow.add_edge("agent_loop", END)
    return workflow.compile()


_COMPILED_GRAPH = _build_graph()


def run_agent(db: Session, conversation_id: str, question: str) -> str:
    result = _COMPILED_GRAPH.invoke({"conversation_id": conversation_id, "question": question, "db": db})
    return result.get("answer")
