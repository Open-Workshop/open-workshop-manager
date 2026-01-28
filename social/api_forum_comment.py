from fastapi import APIRouter
from ow_config import MAIN_URL


router = APIRouter()


@router.post(MAIN_URL+"/add/forum/comment", tags=["Comment"])
async def add_forum_comment():
    """
    Тестовая функция
    """
    return 0

@router.post(MAIN_URL+"/edit/forum/comment", tags=["Comment"])
async def edit_forum_comment():
    """
    Тестовая функция
    """
    return 0

@router.post(MAIN_URL+"/reputation/forum/comment", tags=["Comment"])
async def reputation_forum_comment():
    """
    Тестовая функция
    """
    return 0

@router.post(MAIN_URL+"/reaction/forum/comment", tags=["Comment"])
async def reaction_forum_comment():
    """
    Тестовая функция
    """
    return 0

@router.delete(MAIN_URL+"/delete/forum/comment", tags=["Comment"])
async def delete_forum_comment():
    """
    Тестовая функция
    """
    return 0
