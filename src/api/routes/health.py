from fastapi import APIRouter, Response, status

router = APIRouter()


@router.get("/healthz")
def healthz():
    return Response(status_code=status.HTTP_200_OK)
