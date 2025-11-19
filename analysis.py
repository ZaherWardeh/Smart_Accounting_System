import pandas as pd
from sqlalchemy.orm import Session, selectinload
from google import genai
from dotenv import load_dotenv
import os
from models import TransactionsDetail
from fastapi import HTTPException, status
import json
import re

load_dotenv()

client = None
try:
    API_Key = os.getenv("API_KEY") 
    client = genai.Client(api_key=API_Key)
    print("Gimini Client was created successfuly")
except Exception as e:
    print (f"Error Creating Gimini Client:{e}")


def get_financial_summary(db: Session):
    transactions = db.query(TransactionsDetail)\
     .options(selectinload(TransactionsDetail.rsAccounts)).all()
    data = [
        {
            "credit": t.credit,
            "debit": t. debit,
            "acc_id": t.acc_id,
            "description": t.description,
            "acc_closeIn": t.rsAccounts.closeIn,
            "acc_parent_account": t.rsAccounts.parentAccount
        }
        for t in transactions
    ]    

    df = pd.DataFrame(data)

    if df.empty:
        return {"Message":"لا يوجد بيانات لتحليلها"}

    df["credit"] = pd.to_numeric(df["credit"],errors="coerce").fillna(0)
    df["debit"] = pd.to_numeric(df["debit"],errors="coerce").fillna(0)

    total_income =df[df["acc_closeIn"].isin([1,2])]["credit"].sum()
    total_expense = df[df["acc_closeIn"].isin([1,2])]["debit"].sum()
    balance = total_income - total_expense

    return {
        "Total Income": total_income,
        "Total Expense": total_expense,
        "Balance": balance,
    }

# AI Section

def intent_analysis(question: str) -> str:
    prompt = f"""
    أنت مساعد ذكي داخل برنامج محاسبة. وظيفتك الأولى هي تحليل نية المستخدم من السؤال فقط بدون تنفيذ الطلب، وتحديد تصنيف واحد من الفئات التالية:

1. تحية / ترحيب (Greeting)
   - مثل: مرحبا، أهلًا، كيفك، شو بتعمل؟

2. سؤال محاسبي (Accounting Inquiry)
   - مثل: كشف حساب، ميزان مراجعة، أرصدة، فواتير، حسابات مدينة/دائنة، قيود يومية، حركة صناديق، حركة نقدية، تقارير محاسبية.

3. تحليل مالي (Financial Analysis)
   - مثل: تحليل سيولة، تحليل ربحية، مقارنة شهرية، انحرافات مالية، توقعات مالية، تحليل مصاريف، KPIs.

4. طلب متعلق بالبيانات (Data Request)
   - أي طلب يتطلب استخراج بيانات، تلخيص بيانات، أو معايير يراد تطبيقها على بيانات محاسبية.
   - مثل: عطيني المعاملات فوق 1000، لخصلي حركة شهر 3، جمعلي المصاريف حسب التصنيف.

6. خارج نطاق النظام (Out of Scope)
   - أي سؤال غير متعلق بالمحاسبة أو البرنامج
   - مثل: أخبار الطقس، اعملي قصة، كيف أطبخ، معلومات عامة، نصائح شخصية، مواضيع سياسية.

مهم:
- أعد لي المخرجات دائمًا بصيغة JSON فقط، وبدون أي نص إضافي.
- صيغة JSON يجب أن تكون:

{{
  "intent": "Greeting | Accounting Inquiry | Financial Analysis | Data Request | Out of Scope",
  "confidence": "low | medium | high",
  "reason": "سبب التصنيف"
}}
ملاحظات إضافية:
1- التزم فقط بالجواب والرد بصيغة JSON المقدمة دون إضافة أي كلمة إضافية عنها
2- التزم بالخيارات المقدمة فقط في التصنيف
ابدأ الآن بتحليل نية المستخدم فقط، السؤال هو: '{question}'
"""
    response = exec_prompt(prompt)
    return response.text

def welcoming_proc(question: str) -> str:
    prompt = f"""
أنت مساعد برنامج محاسبة ذكي. أهم قاعدة يجب عليك الالتزام بها هي:

قاعدة اللغة:
يجب أن تجيب دائماً باللغة نفسها التي استخدمها المستخدم في سؤاله،
سواء كانت عربية، إنكليزية، فرنسية أو أي لغة أخرى — بدون أي استثناء.

 يمنع عليك الرد باللغة العربية إذا كان سؤال المستخدم بلغة مختلفة.

----------------------------------

اسمك هو "ريما" وأنت محاسبة ذكية داخل برنامج محاسبة، ومهمتك تحليل بيانات المستخدم والإجابة على استفساراته المالية.

بيانات إضافية:
سؤال المستخدم هو: '{question}'

ابدأ الآن الإجابة وفق لغة المستخدم حصراً.
"""
    response = exec_prompt(prompt)
    
    return response.text
   
def inquiry_proc(db: Session, question: str, intent: str) -> str:  
    transactions = db.query(TransactionsDetail)\
    .options(selectinload(TransactionsDetail.rsAccounts),
             selectinload(TransactionsDetail.rsTransactionsMaster))\
        .all()
    
    data = [
        {
            "credit": t.credit,
            "debit": t. debit,
            "acc_id": t.acc_id,
            "acc_name": t.rsAccounts.name,
            "description": t.description or t.rsTransactionsMaster.notes,
            "acc_closeIn": t.rsAccounts.closeIn,
            "acc_parent_account": t.rsAccounts.parentAccount,
            "transaction_date": (
                t.rsTransactionsMaster.date.strftime("%Y-%m-%d") if t.rsTransactionsMaster and t.rsTransactionsMaster.date
                  else None)
        }
        for t in transactions
    ]    

    df = pd.DataFrame(data)
    df['transaction_date'] = pd.to_datetime(df['transaction_date'], errors='coerce')
    prompt = f"""
أنت مساعد متخصص بتوليد كود Python آمن لمعالجة DataFrame باسم df.

مهمتك هي:
- استنتاج شروط الفلترة من سؤال المستخدم.
- توليد كود فلترة فقط دون أي عمليات أخرى.
- الكود يجب ألا يحتوي على أي imports أو تعريف متغيرات جديدة.
- لا تستخدم exec أو open أو أي شيء خارج نطاق Pandas.

صيغة الرد يجب أن تكون Python فقط، بدون أي شرح أو نص إضافي.

    سؤال المستخدم هو:'{question}'
    بينات إضافية:
    إليك أول 5 أسطر من البيانات المحاسبة بصيغة Data Frame:
    {df.head().to_string(index=False)}
    إبدأ الآن بتوليد كود الفلترة المطلوب بناءً على سؤال المستخدم.
"""
    response = exec_prompt(prompt)
    code_from_ai = re.sub(r"```python|```", "",response.text).strip()
    print("Generated code from AI:\n", code_from_ai)
    exec(code_from_ai)
    print("Summerizing code was done successfully.")
    prompt = f"""
أنت مساعد متخصص بتحليل البيانات المحاسبية.

مهمتك:
- تحديد إن كان ينبغي تلخيص البيانات قبل إرسالها إلى نموذج AI.
- إذا لازم → تولّد كود Pandas للتلخيص.
- إذا غير ضروري → أعد "No" فقط.

ملاحظات:
1- توليد كود فلترة فقط دون أي عمليات أخرى.
2- الكود يجب ألا يحتوي على أي imports أو تعريف متغيرات جديدة.
3- لا تستخدم exec أو open أو أي شيء خارج نطاق Pandas.
4- استخدم نفس Data Frame باسم df ولا تقم بتعريف أي Data Frame جديد.

صيغة الرد يجب أن تكون JSON فقط:

{{
  "Code_Generated": "Yes" أو "No",
  "Code_Details": "الكود هنا أو null"
}}

معايير اتخاذ القرار:
- إذا السؤال عام أو تحليلي → Yes
- إذا السؤال بحاجة تلخيص (شهور، أيام، Accounts) → Yes
- إذا حجم البيانات كبير (> 5000 صف) → Yes
- إذا السؤال بسيط جداً → No

سؤال المستخدم:
{question}

أول 5 صفوف من df:
{df.head().to_string(index=False)}

عدد الصفوف: {len(df)}
إبدأ الآن باتخاذ القرار المناسب.
"""
    response = exec_prompt(prompt)
    j_son = json.loads(re.sub(r"```json|```", "",response.text).strip())
    code_generated = j_son.get("Code_Generated")
    code_details = j_son.get("Code_Details")
    print(f"Code Generated:{code_generated}, Code:{code_details}")
    if code_generated == "Yes":
        exec(code_details)
    title = "محاسب ذكي" if intent == "Accounting Inquiry" else "محلل مالي ذكي" if intent == "Financial Analysis" else "مساعد بيانات محاسبية ذكي"
    prompt = f"""
     أنت  {title} تحلل بيانات محاسبية ومالية. أهم قاعدة يجب عليك الالتزام بها هي:
        قاعدة اللغة:
        يجب أن تجيب دائماً باللغة نفسها التي استخدمها المستخدم في سؤاله،
        سواء كانت عربية، إنكليزية، فرنسية أو أي لغة أخرى — بدون أي استثناء.
        يمنع عليك الرد باللغة العربية إذا كان سؤال المستخدم بلغة مختلفة.
        
     البيانات التالية تمثل السجلات المحاسبية النهائية بعد الفلترة والتلخيص:
     {df.to_json(orient="records")}

     سؤال المستخدم:
     {question}

     اعتمد فقط على البيانات أعلاه. أجب بطريقة واضحة وفق لغة المستخدم.
"""
    response = exec_prompt(prompt)
    return response.text

def prompt_Ambiguity_Response(question: str) -> str:
    prompt = f"""
    أنت مساعد ذكي داخل برنامج محاسبة. وظيفتك هي الرد على المستخدم بطريقة مهذبة تفيد بعدم قدرتك على فهم السؤال والإجابة عليه وسأله بلطف أن يعيد صياغة السؤال بطريقة أبسط تمكنك من فهم مراده.
. أهم قاعدة يجب عليك الالتزام بها هي:       
        قاعدة اللغة:
        يجب أن تجيب دائماً باللغة نفسها التي استخدمها المستخدم في سؤاله،
        سواء كانت عربية، إنكليزية، فرنسية أو أي لغة أخرى — بدون أي استثناء.
        يمنع عليك الرد باللغة العربية إذا كان سؤال المستخدم بلغة مختلفة.    
    سؤال المستخدم هو: '{question}'
    أجب بطريقة مهذبة توضح عدم قدرتك على الفهم وتطلب منه إعادة صياغة سؤاله، وفق اللغة التي استخدمها في سؤاله.
    """
    response = exec_prompt(prompt)
    return response.text

def prompt_Out_of_Scope_Response(question: str) -> str:
    prompt = f"""
    أنت مساعد ذكي داخل برنامج محاسبة. اتبع القواعد التالية بدقة:

    قاعدة اللغة:
    يجب أن تجيب دائمًا باللغة نفسها التي استخدمها المستخدم، دون أي استثناء.

    قاعدة التفاعل الاجتماعي:
    إذا كانت رسالة المستخدم:
    - تحية
    - شكر
    - مجاملة
    - رد قصير مثل: تمام، ممتاز، أوكي، يسلمو
    - أي كلام اجتماعي لا يحتوي على طلب أو سؤال
    فعليك الرد بشكل طبيعي ولطيف، **دون أي اعتذار**.

    قاعدة الأسئلة خارج المحاسبة:
    إذا احتوت رسالة المستخدم على **طلب فعلي** أو **سؤال** لا يتعلق بالمحاسبة أو التحليل المالي،
    عندها فقط يجب أن تعتذر بلباقة وتقول إنه خارج نطاق اختصاصك.

    ملاحظة مهمة:
    إذا كانت رسالة المستخدم قصيرة ولا تحتوي أي طلب (مثل: شكراً، تمام، يسعدك)، فهذا ليس سؤالاً خارج المحاسبة، ولا يجب الاعتذار.

    رسالة المستخدم هي: '{question}'
    الرجاء الرد الآن وفق القواعد المذكورة أعلاه.
    """
    response = exec_prompt(prompt)
    return response.text

def exec_prompt(prompt: str):
    global client
    if not client:
        raise HTTPException(status_code=status.HTTP_417_EXPECTATION_FAILED,
                            detail="Google client could not attached, check your API key")
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role":"user","parts": [{"text": prompt}]}]
        )
    except Exception as e: 
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Google client could not manage your request:'{str(e)}'")
    
    return response

def analyze_with_ai(db: Session, question: str):
    intentAnalysis = re.sub(r"```json|```", "",intent_analysis(question)).strip()
    response = json.loads(intentAnalysis)
    intent = response.get("intent")
    confidence = response.get("confidence")
    reason = response.get("reason")
    print(f"Intent:{intent}, Confidence:{confidence}, Reason:{reason}")
    if confidence == "low":
        return prompt_Ambiguity_Response(question)
    if intent == "Out of Scope":
        return prompt_Out_of_Scope_Response(question)
    elif intent == "Greeting":
        return welcoming_proc(question)
    elif intent == "Accounting Inquiry" or intent == "Financial Analysis" or intent == "Data Request":
        return inquiry_proc(db, question, intent)
