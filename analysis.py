import pandas as pd
from sqlalchemy.orm import Session, joinedload
from google import genai
from dotenv import load_dotenv
import os
from models import Accounts,TransactionsMaster,TransactionsDetail

#client = OpenAI(api_key="", base_url="http://localhost:11434/v1")
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
     .options(joinedload(TransactionsDetail.rsAccounts)).all()
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

def analyze_with_ai(db: Session, question: str):
    transactions = db.query(TransactionsDetail)\
     .options(joinedload(TransactionsDetail.rsAccounts)).all()
    
    data = [
        {
            "credit": t.credit,
            "debit": t. debit,
            "acc_id": t.acc_id,
            "acc_name": t.rsAccounts.name,
            "description": t.description,
            "acc_closeIn": t.rsAccounts.closeIn,
            "acc_parent_account": t.rsAccounts.parentAccount
        }
        for t in transactions
    ]    

    df = pd.DataFrame(data)

#    summary = get_financial_summary(db)

#    context = f"""
#    هذه هي ملخصات البيانات المالية:
#    - إجمالي الإيرادات: {summary['Total Income']}
#    - إجمالي المصاريف: {summary['Total Expense']}
#    - الرصيد الصافي: {summary['Balance']}
#    """

    print(df.head().to_string(index=False))
    prompt = f"""
    أنت مساعد مالي ذكي تحلل بيانات محاسبية.
    البيانات التالية تمثل جميع السجلات بصيغة JSON:
    {df.to_json(orient="records")}

    سؤال المستخدم:
    {question}

    اعتمد فقط على البيانات أعلاه. أجب بطريقة تحليلية وواضحة باللغة التي يطلبها المستخدم.
    """
    global client
    if client is None:
        # إرجاع رسالة خطأ واضحة للمستخدم
        return {"answer": "تعذر إجراء التحليل: لم يتم ربط تطبيقنا بـ Gemini API بنجاح (يرجى مراجعة مفتاح API)."}
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[{"role":"user","parts": [{"text": prompt}]}]
        )
    except Exception as e:
        return f"فشل الاستدعاء من Gemini API: {str(e)}"

    return response.text