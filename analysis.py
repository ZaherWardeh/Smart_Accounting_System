import pandas as pd
from sqlalchemy.orm import Session, selectinload
from google import genai
from dotenv import load_dotenv
import os
from models import TransactionsDetail
from fastapi import HTTPException, status

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
