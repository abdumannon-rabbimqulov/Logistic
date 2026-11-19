"""/drivers — haydovchi kabineti va mashina turlari.

Driver: profil yaratish (POST /profile), kabinet (/me), daromad, balans tarixi,
jonli GPS (WS /ws/location). Mashina turlari: o'qish hamma uchun, yozish faqat admin.
"""

import logging
import os
import uuid
from typing import List, Optional

import aiofiles
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from Admin_panel.validation import is_admin
from config.config import (
    STATIC_PATH,
    UPLOAD_DIR,
    get_db,
)
from driver import crud, schemas
from driver.models import Driver
from driver.profile import build_driver_profile
from services import billing
from users.auth import get_current_user
from users.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/drivers", tags=["Haydovchilar (Drivers)"])

# Jonli GPS WebSocket'i (`/drivers/ws/location`) endi `tracking_service` da — core
# faqat `/drivers/me/tracking-identity` orqali avtorizatsiya beradi.

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB — rasm yuklash uchun maksimal hajm
ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


async def _ensure_truck_type_name_free(
    db: AsyncSession, name: str, *, exclude_id: Optional[int] = None
) -> None:
    """Nom band bo'lsa — tushunarli 409. Ilgari DB'ning unique xatosi umumiy
    "Database conflict" bo'lib qaytardi va adminlarga Telegram alert yuborardi."""
    existing = await crud.find_truck_type_by_name(db, name, exclude_id=exclude_id)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"\"{existing.name}\" nomli mashina turi allaqachon bor. Boshqa nom kiriting "
            "yoki mavjudini tahrirlang.",
        )


# Fayl turi brauzer yuborgan Content-Type'ga qarab EMAS, faylning o'z baytlariga
# qarab aniqlanadi: ba'zi brauzer/WebView'lar WebP'ni `application/octet-stream`
# deb yuboradi va rasm rad etilardi. Bu, shuningdek, rasm deb niqoblangan boshqa
# fayllarni ham to'xtatadi.
def _detect_image_ext(head: bytes) -> Optional[str]:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    return None


@router.post("/truck-types", response_model=schemas.TruckTypeResponse, status_code=status.HTTP_201_CREATED, summary="Yangi mashina turi qo'shish,admin uchun")
async def create_truck_type(
    data: schemas.TruckTypeCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(is_admin),
):
    await _ensure_truck_type_name_free(db, data.name)
    return await crud.create_truck_type(db, data)

@router.get("/truck-types", response_model=List[schemas.TruckTypeResponse], summary="Barcha mashina turlarini olish,hamma uchun")
async def list_truck_types(db: AsyncSession = Depends(get_db)):
    return await crud.get_all_truck_types(db)

@router.post("/truck-types/image", response_model=dict, summary="Truck type rasmini yuklash, admin uchun")
async def upload_truck_type_image(
    file: UploadFile = File(...),
    admin: User = Depends(is_admin),
):
    # Hajm limiti — DoS/disk to'ldirilishining oldini olish uchun cheklab o'qiymiz.
    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Fayl juda katta (maks. 5MB)",
        )

    file_ext = _detect_image_ext(contents[:16])
    if file_ext not in ALLOWED_IMAGE_EXTS:
        raise HTTPException(
            status_code=400,
            detail="Faqat rasm yuklash mumkin: PNG, JPG, WebP yoki GIF",
        )

    unique_filename = f"truck_type_{uuid.uuid4()}{file_ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_filename)
    async with aiofiles.open(file_path, "wb") as buffer:
        await buffer.write(contents)

    return {"url": f"{STATIC_PATH}/{unique_filename}"}

@router.patch("/truck-types/{pk}", response_model=schemas.TruckTypeResponse, summary="Mashina turini tahrirlash,admin uchun")
async def update_truck_type(
    pk: int,
    data: schemas.TruckTypeUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(is_admin),
):
    if data.name is not None:
        await _ensure_truck_type_name_free(db, data.name, exclude_id=pk)
    obj = await crud.update_truck_type(db, pk, data)
    if not obj:
        raise HTTPException(status_code=404, detail="Truck type not found")
    return obj

@router.delete("/truck-types/{pk}", status_code=status.HTTP_204_NO_CONTENT, summary="Mashina turini o'chirish,admin uchun")
async def delete_truck_type(
    pk: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(is_admin),
):
    await crud.delete_truck_type(db, pk)
    return None


@router.post("/profile", response_model=schemas.DriverResponse, status_code=status.HTTP_201_CREATED, summary="Haydovchi profilini yaratish")
async def create_driver_profile(
    data: schemas.DriverCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = await crud.get_driver_by_user_id(db, current_user.id)
    if existing:
        raise HTTPException(status_code=400, detail="Driver profile already exists")

    if data.phone_number:
        current_user.phone_number = data.phone_number
        await db.commit()

    return await crud.create_driver(db, data, user_id=current_user.id)

async def _require_driver(db: AsyncSession, current_user: User) -> Driver:
    driver = await crud.get_driver_by_user_id(db, current_user.id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver profile not found")
    return driver


@router.get(
    "/me",
    response_model=schemas.DriverProfileResponse,
    summary="Mening haydovchi profilim (kabinet)",
)
async def get_my_driver_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    driver = await _require_driver(db, current_user)
    return await build_driver_profile(db, current_user, driver)


@router.get(
    "/me/earnings",
    response_model=List[schemas.DriverEarningItem],
    summary="Mening daromadlarim: har bir yakunlangan buyurtma va undan olingan komissiya",
)
async def list_my_earnings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """"Daromad" ekrani uchun: buyurtma nomi/manzillari, summa va ushlab qolingan komissiya.

    Komissiya `balance_transactions` jadvalidan (`ORDER_COMMISSION`) olinadi va bitta
    so'rovda buyurtmaga bog'lanadi — frontend har qator uchun alohida so'rov
    yubormasligi kerak.
    """
    await _require_driver(db, current_user)
    return await billing.list_driver_earnings(db, current_user.id, skip=skip, limit=limit)


@router.get(
    "/me/balance/transactions",
    response_model=List[schemas.BalanceTransactionItem],
    summary="Mening balans tarixim (komissiya yechilishi va to'ldirishlar)",
)
async def list_my_balance_transactions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    """Haydovchi kabinetidagi (Profil sahifasi) balans tarixi — faqat o'z yozuvlari."""
    await _require_driver(db, current_user)
    return await billing.list_balance_transactions(db, current_user.id, skip=skip, limit=limit)


@router.patch("/me", response_model=schemas.DriverProfileResponse, summary="Profilni tahrirlash")
async def update_my_driver_profile(
    data: schemas.DriverUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    driver = await _require_driver(db, current_user)

    dump = data.model_dump(exclude_unset=True)
    dump.pop("last_latitude", None)
    dump.pop("last_longitude", None)

    # Bloklangan (masalan qarz tufayli) haydovchi liniyaga chiqa olmaydi
    if driver.is_blocked and (dump.get("is_available") or dump.get("is_live_location_active")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Siz bloklangansiz — liniyaga chiqa olmaysiz. Sababi: " + (driver.block_reason or "noma'lum"),
        )

    if dump:
        await crud.update_driver(db, driver.id, schemas.DriverUpdate(**dump))
        driver = await crud.get_driver(db, driver.id)
    await db.refresh(current_user)
    return await build_driver_profile(db, current_user, driver)




@router.get("/me/tracking-identity", summary="Tracking servisi uchun: haydovchi identifikatsiyasi")
async def driver_tracking_identity(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """`tracking_service` WebSocket ulanishida (bir marta) shu endpoint orqali tokenni
    tekshiradi: bazaga u o'zi ulanmaydi. Bloklangan haydovchi 403 oladi."""
    driver = await crud.get_driver_by_user_id(db, current_user.id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Haydovchi profili topilmadi")
    if driver.is_blocked:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Haydovchi bloklangan")
    return {
        "driver_id": driver.id,
        "user_id": current_user.id,
        "full_name": current_user.full_name,
        "truck_number": driver.truck_number,
        "truck_type_id": driver.truck_type_id,
    }
