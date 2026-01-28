from fastapi import APIRouter
from ow_config import MAIN_URL


router = APIRouter()

@router.get(MAIN_URL+"/list/forum/", tags=["Forum"])
async def list_forums():
    """
    Тестовая функция
    """
    return 0

@router.get(MAIN_URL+"/list/comment/{forum_id}", tags=["Forum"])
async def list_comment(forum_id: int):
    """
    Тестовая функция
    """
    return 0

@router.post(MAIN_URL+"/add/forum", tags=["Forum"])
async def add_forum():
    """
    Тестовая функция
    """
    return 0

@router.post(MAIN_URL+"/edit/forum", tags=["Forum"])
async def edit_forum():
    """
    Тестовая функция
    """
    return 0

@router.post(MAIN_URL+"/reputation/forum", tags=["Forum"])
async def reputation_forum():
    """
    Тестовая функция
    """
    return 0

@router.delete(MAIN_URL+"/delete/forum", tags=["Forum"])
async def delete_forum():
    """
    Тестовая функция
    """
    return 0
