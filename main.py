import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Boolean, Column, Integer, String, DateTime, ForeignKey, func, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost/restaurant")
JWT_SECRET = os.getenv("JWT_SECRET", "supersecretjwt")
JWT_ALGORITHM = "HS256"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# MODELE SQLALCHEMY
class ManagerUser(Base):
    __tablename__ = "manager_user"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    role = Column(String, default="manager")

class MenuCategory(Base):
    __tablename__ = "menu_category"
    id = Column(Integer, primary_key=True, index=True)
    name_pl = Column(String)
    name_en = Column(String)
    image_url = Column(String, nullable=True)

class MenuItem(Base):
    __tablename__ = "menu_item"
    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, ForeignKey("menu_category.id"))
    name_pl = Column(String)
    name_en = Column(String)
    price_cents = Column(Integer)
    image_url = Column(String, nullable=True)
    is_available = Column(Boolean, default=True)

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_number = Column(Integer)
    status = Column(String)
    type = Column(String)
    created_at = Column(DateTime)
    ready_at = Column(DateTime, nullable=True)
    language = Column(String)

class OrderItem(Base):
    __tablename__ = "order_item"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    menu_item_id = Column(Integer, ForeignKey("menu_item.id"))
    quantity = Column(Integer)

class OrderEventLog(Base):
    __tablename__ = "order_event_log"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    event_type = Column(String)
    terminal_name = Column(String)
    timestamp = Column(DateTime)
    new_status = Column(String)

# SCHEMATY Pydantic
class Token(BaseModel):
    access_token: str

class UserMe(BaseModel):
    id: int
    username: str
    roles: List[str]

class MenuCategorySchema(BaseModel):
    id: Optional[int]
    name_pl: str
    name_en: str
    image_url: Optional[str]
    class Config:
        orm_mode = True

class MenuItemSchema(BaseModel):
    id: Optional[int]
    category_id: int
    name_pl: str
    name_en: str
    price_cents: int
    image_url: Optional[str]
    is_available: Optional[bool] = True
    class Config:
        orm_mode = True

class OrderItemSchema(BaseModel):
    id: int
    menu_item_id: int
    name: str
    quantity: int

class OrderEventSchema(BaseModel):
    id: int
    event_type: str
    terminal_name: str
    timestamp: datetime
    new_status: str

class OrderSchema(BaseModel):
    id: int
    order_number: int
    status: str
    type: str
    created_at: datetime
    ready_at: Optional[datetime]
    language: str
    class Config:
        orm_mode = True

class OrderDetailsSchema(OrderSchema):
    items: List[OrderItemSchema]
    events: List[OrderEventSchema]

# JWT
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

def create_access_token(data: dict, expires_delta: timedelta = timedelta(hours=12)):
    import jwt  # PyJWT
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + expires_delta})
    return jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(lambda: SessionLocal())):
    import jwt  # PyJWT
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = db.query(ManagerUser).filter(ManagerUser.id == int(user_id)).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")

# FASTAPI APP
app = FastAPI()

# --- CORS middleware (MUSI być przed routerami!) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://happy-coast-068f78503.2.azurestaticapps.net/"],  # produkcyjnie: ["https://victorious-bush-0d4d65503.1.azurestaticapps.net"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Endpoints ---
@app.post("/auth/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(lambda: SessionLocal())):
    user = db.query(ManagerUser).filter(ManagerUser.username == form_data.username).first()
    if not user or user.password_hash != form_data.password:  # produkcyjnie: sprawdź hash!
        raise HTTPException(status_code=400, detail="Invalid credentials")
    token = create_access_token({"sub": str(user.id), "role": user.role})  # sub = string!
    return {"access_token": token}

@app.get("/auth/me", response_model=UserMe)
def get_me(current_user: ManagerUser = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username, "roles": [current_user.role]}

@app.get("/menu/categories", response_model=List[MenuCategorySchema])
def get_categories(db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    return db.query(MenuCategory).all()

@app.post("/menu/categories", response_model=MenuCategorySchema)
def add_category(cat: MenuCategorySchema, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    obj = MenuCategory(**cat.dict(exclude_unset=True))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@app.put("/menu/categories/{id}", response_model=MenuCategorySchema)
def update_category(id: int, upd: MenuCategorySchema, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    obj = db.query(MenuCategory).filter(MenuCategory.id == id).first()
    if not obj: raise HTTPException(404)
    for k, v in upd.dict(exclude_unset=True).items(): setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj

@app.delete("/menu/categories/{id}")
def delete_category(id: int, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    obj = db.query(MenuCategory).filter(MenuCategory.id == id).first()
    if not obj: raise HTTPException(404)
    db.delete(obj)
    db.commit()
    return {}

@app.get("/menu/items", response_model=List[MenuItemSchema])
def get_menu_items(db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    return db.query(MenuItem).all()

@app.post("/menu/items", response_model=MenuItemSchema)
def add_menu_item(item: MenuItemSchema, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    obj = MenuItem(**item.dict(exclude_unset=True))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

@app.put("/menu/items/{id}", response_model=MenuItemSchema)
def update_menu_item(id: int, upd: MenuItemSchema, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    obj = db.query(MenuItem).filter(MenuItem.id == id).first()
    if not obj: raise HTTPException(404)
    for k, v in upd.dict(exclude_unset=True).items(): setattr(obj, k, v)
    db.commit()
    db.refresh(obj)
    return obj

@app.delete("/menu/items/{id}")
def delete_menu_item(id: int, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    obj = db.query(MenuItem).filter(MenuItem.id == id).first()
    if not obj: raise HTTPException(404)
    db.delete(obj)
    db.commit()
    return {}

@app.post("/menu/items/{id}/block")
def block_menu_item(id: int, is_available: bool, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    obj = db.query(MenuItem).filter(MenuItem.id == id).first()
    if not obj: raise HTTPException(404)
    obj.is_available = is_available
    db.commit()
    db.refresh(obj)
    return {"is_available": obj.is_available}

@app.get("/orders", response_model=List[OrderSchema])
def get_orders(
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(lambda: SessionLocal()),
    _: ManagerUser = Depends(get_current_user)
):
    q = db.query(Order)
    if status: q = q.filter(Order.status == status)
    if date_from: q = q.filter(Order.created_at >= date_from)
    if date_to: q = q.filter(Order.created_at <= date_to)
    return q.all()

@app.get("/orders/{order_id}", response_model=OrderDetailsSchema)
def get_order_details(order_id: int, db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order: raise HTTPException(404)
    items = (
        db.query(OrderItem, MenuItem)
        .join(MenuItem, OrderItem.menu_item_id == MenuItem.id)
        .filter(OrderItem.order_id == order_id)
        .all()
    )
    items_schema = [OrderItemSchema(
        id=oi.id, menu_item_id=oi.menu_item_id, name=mi.name_pl, quantity=oi.quantity
    ) for oi, mi in items]
    events = db.query(OrderEventLog).filter(OrderEventLog.order_id == order_id).all()
    events_schema = [OrderEventSchema.from_orm(e) for e in events]
    return OrderDetailsSchema(
        **order.__dict__,
        items=items_schema,
        events=events_schema
    )

@app.get("/stats/orders/daily")
def orders_daily(date: Optional[str] = Query(None), db: Session = Depends(lambda: SessionLocal()), _: ManagerUser = Depends(get_current_user)):
    day = date or datetime.utcnow().date()
    results = (
        db.query(OrderEventLog.terminal_name, func.count().label("orders_count"))
        .filter(OrderEventLog.event_type == "ready")
        .filter(func.date(OrderEventLog.timestamp) == day)
        .group_by(OrderEventLog.terminal_name)
        .all()
    )
    return {"terminal_stats": [{"terminal_name": t, "orders_count": c} for t, c in results]}

@app.get("/stats/menu-items/top")
def top_menu_items(
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: Session = Depends(lambda: SessionLocal()),
    _: ManagerUser = Depends(get_current_user)
):
    q = db.query(MenuItem.id, MenuItem.name_pl, func.sum(OrderItem.quantity).label("sold_count")) \
        .join(OrderItem, MenuItem.id == OrderItem.menu_item_id) \
        .join(Order, OrderItem.order_id == Order.id)
    if date_from:
        q = q.filter(Order.created_at >= date_from)
    if date_to:
        q = q.filter(Order.created_at <= date_to)
    q = q.group_by(MenuItem.id, MenuItem.name_pl).order_by(func.sum(OrderItem.quantity).desc()).limit(10)
    return [
        {"menu_item_id": id, "name": name, "sold_count": sold}
        for id, name, sold in q.all()
    ]

@app.get("/test-db")
def test_db_connection():
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"db": "ok"}
    except Exception as e:
        return {"db": "error", "details": str(e)}

@app.get("/hello-debug")
def hello_debug():
    return {"msg": "hello from new code"}

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)

@app.get("/debug-secret")
def debug_secret():
    import os
    return {"JWT_SECRET": os.getenv("JWT_SECRET")}
