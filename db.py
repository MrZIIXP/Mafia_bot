from sqlalchemy import create_engine, String, Integer, BigInteger, Column
from sqlalchemy.orm import declarative_base


Base = declarative_base()
url = 'postgresql://postgres:ziedullo000@localhost:5432/Exan_1'
engine = create_engine(url)

class Users(Base):
   __tablename__ = 'users'

   id	= Column(Integer, primary_key=True)
   tg_id	= Column(BigInteger, unique=True)
   username	= Column(String, nullable=False)
   roles = Column(String, nullable=True)
   active_game = Column(Integer, nullable=True)



class Game(Base):
   __tablename__ = 'game'

   id	= Column(Integer, primary_key=True)	
   player_count = Column(Integer, default=1)







Base.metadata.create_all(engine)