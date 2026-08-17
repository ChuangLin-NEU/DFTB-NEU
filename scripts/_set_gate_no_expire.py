import sqlite3

db = r"D:\dftb-neu\data\classroom\classroom.sqlite3"
c = sqlite3.connect(db)
print("before", c.execute("select session_days from gate where id=1").fetchone())
c.execute("update gate set session_days=0 where id=1")
c.commit()
print("after", c.execute("select session_days from gate where id=1").fetchone())
c.close()
