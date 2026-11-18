from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_serializer, field_validator, model_validator
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Optional
from utils.validation import CaseInsensitiveSchemaEnum




class DriverVerificationStatus(CaseInsensitiveSchemaEnum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class DocumentType(CaseInsensitiveSchemaEnum):
    DRIVER_LICENSE    = "DRIVER_LICENSE"
    PASSPORT          = "PASSPORT"
    TRUCK_TECH_PASS   = "TRUCK_TECH_PASS"
    TRUCK_INSURANCE   = "TRUCK_INSURANCE"
    MEDICAL_CERT      = "MEDICAL_CERT"
    OTHER             = "OTHER"


# ── Mashina turi ─────────────────────────────────────────────────────────────
# Chegaralar DB ustunlariga mos (driver/models.py TruckType). Ilgari sxemada hech
# qanday chegara yo'q edi: 50+ belgili nom yoki 10 000+ tonna DB'da "numeric field
# overflow" bilan 500 berardi, bo'sh nom va manfiy og'irlik esa saqlanib qolardi.
TruckName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Capacity = Annotated[Decimal, Field(gt=0, le=Decimal("9999.99"))]       # Numeric(6, 2)
Dimension = Annotated[Decimal, Field(gt=0, le=Decimal("999.99"))]       # Numeric(5, 2), metr
Money = Annotated[Decimal, Field(ge=0, le=Decimal("9999999999.99"))]    # Numeric(12, 2), UZS
Pallets = Annotated[int, Field(ge=0, le=10_000)]


class TruckTypeCreate(BaseModel):
    name: TruckName
    max_weight: Capacity = Field(description="Maksimal og'irlik, tonna")
    max_volume: Capacity = Field(description="Maksimal hajm, m³")
    length: Optional[Dimension] = None
    width: Optional[Dimension] = None
    height: Optional[Dimension] = None
    pallet_capacity: Optional[Pallets] = None
    base_price: Money = Field(Decimal("0"), description="Boshlang'ich narx, UZS")
    price_per_km: Money = Field(Decimal("0"), description="1 km uchun narx, UZS")
    min_price: Optional[Money] = Field(None, description="Minimal narx (pol), UZS")
    price_per_ton_km: Money = Field(Decimal("0"), description="1 tonna-km narxi, UZS")
    image_url: Optional[str] = Field(None, max_length=512)
    description: Optional[str] = Field(None, max_length=200)
    is_active: bool = True


class TruckTypeUpdate(BaseModel):
    """Qisman yangilash: faqat yuborilgan maydonlar o'zgaradi."""

    name: Optional[TruckName] = None
    max_weight: Optional[Capacity] = None
    max_volume: Optional[Capacity] = None
    length: Optional[Dimension] = None
    width: Optional[Dimension] = None
    height: Optional[Dimension] = None
    pallet_capacity: Optional[Pallets] = None
    base_price: Optional[Money] = None
    price_per_km: Optional[Money] = None
    min_price: Optional[Money] = None
    price_per_ton_km: Optional[Money] = None
    image_url: Optional[str] = Field(None, max_length=512)
    description: Optional[str] = Field(None, max_length=200)
    is_active: Optional[bool] = None

    # DB'da NOT NULL ustunlar: ularga ochiq `null` yuborilsa DB xatosi (IntegrityError)
    # o'rniga oddiy 422 qaytsin.
    _NOT_NULL = ("name", "max_weight", "max_volume", "base_price", "price_per_km", "price_per_ton_km", "is_active")

    @model_validator(mode="after")
    def _reject_null_for_required(self):
        for field in self._NOT_NULL:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"'{field}' bo'sh (null) bo'lishi mumkin emas")
        return self


class TruckTypeResponse(BaseModel):
    """Javob sxemasi ATAYLAB chegarasiz: bazada eski (chegaralardan oldin saqlangan)
    yozuv bo'lsa ham ro'yxat 500 bermasin."""

    id: int
    name: str
    max_weight: Decimal
    max_volume: Decimal
    length: Optional[Decimal] = None
    width: Optional[Decimal] = None
    height: Optional[Decimal] = None
    pallet_capacity: Optional[int] = None
    base_price: Decimal
    price_per_km: Decimal
    min_price: Optional[Decimal] = None
    price_per_ton_km: Decimal = Decimal("0")
    image_url: Optional[str] = None
    description: Optional[str] = None
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DriverBase(BaseModel):
    truck_type_id: int = Field(..., description="Yuk mashinasi turi ID si")
    truck_number: str = Field(..., min_length=3, max_length=20, description="Davlat raqami (60A123BC)")
    truck_year: Optional[int] = Field(None, ge=1980, le=2030, description="Ishlab chiqarilgan yil")
    # Shahar endi ilovada so'ralmaydi (haydovchi joyi jonli GPS orqali aniqlanadi),
    # lekin ustun va moslashtiruvda saqlanib qoldi — eski yozuvlar va bot/admin uchun.
    current_city: Optional[str] = Field(None, max_length=300, description="Hozirgi shahar (ixtiyoriy)")
    current_region: Optional[str] = Field(None, max_length=100, description="Viloyat / Region (ixtiyoriy)")


class DriverCreate(DriverBase):
    phone_number: Optional[str] = Field(None, max_length=20, description="Aloqa raqami (User.phone_number ga yoziladi)")

    @field_validator("phone_number", mode="before")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        from utils.validation import normalize_phone_number
        return normalize_phone_number(v)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "truck_type_id": 2,
                "truck_number": "10Z123ZZ",
                "truck_year": 2021,
                "current_city": "Namangan",
                "current_region": "Namangan viloyati",
                "phone_number": "+998901112233",
            }
        }
    )


class DriverUpdate(BaseModel):
    truck_type_id: Optional[int] = None
    truck_number: Optional[str] = Field(None, max_length=20)
    truck_year: Optional[int] = None
    current_city: Optional[str] = None
    current_region: Optional[str] = None
    is_available: Optional[bool] = None
    is_live_location_active: Optional[bool] = None
    # Liniyaga chiqishda: NULL/berilmasa = hoziroq mavjud, sana berilsa shu sanadan
    # boshlab yuk qabul qilishni bildiradi (services/dispatch.py moslashtiruvchisi uchun).
    available_from_date: Optional[date] = None


class UserStatus(CaseInsensitiveSchemaEnum):
    LIVE = "LIVE"
    OFFLINE = "OFFLINE"


class GpsStatus(CaseInsensitiveSchemaEnum):
    ON = "ON"
    OFF = "OFF"


class DriverProfileResponse(BaseModel):
    """Haydovchi kabineti — ixcham profil (GET /drivers/me, /drivers/profile)."""

    id: int
    user_id: int
    name: str
    rating: float
    balance: str = Field(..., description="Formatlangan balans, masalan: 1 200 000 UZS")
    balance_amount: Decimal
    currency: str = "UZS"
    user_status: UserStatus
    gps_status: GpsStatus
    phone_number: Optional[str] = None
    truck_type_id: int
    truck_type_name: Optional[str] = None
    truck_number: str
    truck_year: Optional[int] = None
    current_city: Optional[str] = None
    current_region: Optional[str] = None
    is_available: bool
    available_from_date: Optional[date] = None
    total_trips: int
    on_time_percent: Decimal
    is_blocked: bool = False


class DriverEarningItem(BaseModel):
    """"Daromad" ekranidagi bitta qator: qaysi buyurtma, qancha va qancha komissiya.

    Ilgari bu ekran faqat buyurtmalar ro'yxatidan qurilardi va komissiyani umuman
    ko'rsatmasdi — haydovchi qo'liga qancha tushganini bilmasdi. Endi buyurtma va
    `balance_transactions` dagi `ORDER_COMMISSION` yozuvi bitta so'rovda birlashtiriladi
    (`services/billing.py list_driver_earnings`).
    """

    order_id: int
    cargo_name: str
    origin_address: Optional[str] = None
    destination_address: Optional[str] = None

    gross_amount: Decimal = Field(..., description="Buyurtma narxi (komissiyagacha)")
    commission_amount: Decimal = Field(
        ..., description="Platforma ushlab qolgan komissiya (musbat son)"
    )
    net_amount: Decimal = Field(..., description="Haydovchi qo'liga tushadigan sof summa")
    currency: str = "UZS"

    completed_at: Optional[datetime] = None


class BalanceTransactionItem(BaseModel):
    """Haydovchining o'z balans harakati (kabinetdagi tarix uchun).

    Admin sxemasidan farqli — `created_by_admin_id` kabi ichki maydonlar berilmaydi.
    """

    id: int
    type: str
    amount: Decimal = Field(..., description="Manfiy = yechildi (komissiya), musbat = to'ldirildi")
    balance_after: Decimal
    order_id: Optional[int] = None
    note: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @field_validator("type", mode="before")
    @classmethod
    def enum_to_value(cls, v):
        return v.value if hasattr(v, "value") else v


class DriverTripScope(CaseInsensitiveSchemaEnum):
    CURRENT = "current"
    COMPLETED = "completed"
    ALL = "all"


class DriverResponse(BaseModel):
    id: int
    user_id: int
    truck_type_id: int
    truck_number: str
    truck_year: Optional[int] = None
    current_city: Optional[str] = None
    current_region: Optional[str] = None
    rating: Decimal
    total_trips: int
    cancel_count: int
    on_time_percent: Decimal
    is_available: bool
    is_blocked: bool
    block_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DriverDocumentBase(BaseModel):
    doc_type: DocumentType = Field(...)
    file_url: str = Field(...)
    file_name: Optional[str] = Field(None)
    expires_at: Optional[datetime] = None

    @field_validator("doc_type", mode="before", check_fields=False)
    @classmethod
    def uppercase_enum_input(cls, v):
        if isinstance(v, str):
            return v.upper()
        if hasattr(v, "value"):
            return str(v.value).upper()
        return v

    @field_serializer("doc_type", check_fields=False)
    def serialize_enum_lower(self, enum_val, _info):
        if hasattr(enum_val, "value"):
            return enum_val.value.lower()
        if isinstance(enum_val, str):
            return enum_val.lower()
        return enum_val

class DriverDocumentCreate(DriverDocumentBase):
    driver_id: int = Field(...)

class DriverDocumentUpdate(BaseModel):
    verification_status: Optional[DriverVerificationStatus] = None
    rejection_reason: Optional[str] = None

    @field_validator("verification_status", mode="before", check_fields=False)
    @classmethod
    def uppercase_enum_input(cls, v):
        if isinstance(v, str):
            return v.upper()
        if hasattr(v, "value"):
            return str(v.value).upper()
        return v

class DriverDocumentResponse(DriverDocumentBase):
    id: int
    driver_id: int
    verification_status: DriverVerificationStatus
    rejection_reason: Optional[str] = None
    verified_by: Optional[int] = None
    verified_at: Optional[datetime] = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

    @field_serializer("verification_status", check_fields=False)
    def serialize_enum_lower(self, enum_val, _info):
        if hasattr(enum_val, "value"):
            return enum_val.value.lower()
        if isinstance(enum_val, str):
            return enum_val.lower()
        return enum_val
