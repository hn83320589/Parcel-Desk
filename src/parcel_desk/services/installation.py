import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from parcel_desk.models import Installation


def get_installation_id(session: Session) -> str:
    """取得這個資料庫的安裝識別碼，第一次呼叫時隨機產生。

    資料庫檔案被複製（備份還原）時識別碼跟著走，所以既有登入仍然有效；
    不同的資料庫（例如正式與示範）識別碼一定不同。
    """
    row = session.get(Installation, 1)
    if row is not None:
        return row.installation_id
    session.add(Installation(id=1, installation_id=str(uuid.uuid4()), created_at=datetime.now(UTC)))
    try:
        session.commit()
    except IntegrityError:
        # 兩個請求同時第一次呼叫：主鍵固定為 1，後到的改讀先寫入的那一列
        session.rollback()
    return session.get(Installation, 1).installation_id
