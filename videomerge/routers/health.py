from fastapi import APIRouter

router = APIRouter(prefix="", tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "healthy"}
