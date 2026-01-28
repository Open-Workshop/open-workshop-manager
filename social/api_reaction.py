from fastapi import APIRouter
from ow_config import MAIN_URL


router = APIRouter()


@router.get(MAIN_URL+"/list/reaction/", tags=["Reaction"])
async def list_reaction():
    """
    Тестовая функция
    """
    return 0


@router.post(MAIN_URL+"/add/reaction", tags=["Reaction"])
async def add_reaction():
    """
    Тестовая функция
    """
    return 0

@router.post(MAIN_URL+"/edit/reaction", tags=["Reaction"])
async def edit_reaction():
    """
    Тестовая функция
    """
    return 0

@router.delete(MAIN_URL+"/delete/reaction", tags=["Reaction"])
async def delete_reaction():
    """
    Тестовая функция
    """
    return 0

