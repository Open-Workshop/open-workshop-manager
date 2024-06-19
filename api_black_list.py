from fastapi import APIRouter
from ow_config import MAIN_URL


router = APIRouter()



@router.post(MAIN_URL+"/list/black/unblock", tags=["Black List"])
async def unblock_user(user_id):
    """
    Тестовая функция
    """
    return 0

@router.delete(MAIN_URL+"/list/black/block", tags=["Black List"])
async def unblock_user(user_id):
    """
    Тестовая функция
    """
    return 0

@router.get(MAIN_URL+"/list/black/get", tags=["Black List"])
async def get_black_list():
    """
    Тестовая функция
    """
    return 0

@router.get(MAIN_URL+"/list/black/in/{user_id}", tags=["Black List"]) # состою ли в ЧС у определенного юзера
async def in_black_list(user_id):
    """
    Тестовая функция
    """
    return 0
