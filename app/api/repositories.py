import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import Repository

logger = structlog.get_logger()

router = APIRouter(prefix="/repositories", tags=["repositories"])


class RepositoryCreate(BaseModel):
    github_full_name: str
    installation_id: int
    default_branch: str = "main"


class RepositoryResponse(BaseModel):
    id: str
    github_full_name: str
    default_branch: str
    installation_id: int
    indexing_status: str
    last_indexed_sha: str | None

    model_config = {"from_attributes": True}


@router.post("", response_model=RepositoryResponse, status_code=201)
async def create_repository(
    data: RepositoryCreate,
    db: AsyncSession = Depends(get_db),
) -> Repository:
    existing = await db.execute(
        select(Repository).where(Repository.github_full_name == data.github_full_name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Repository already exists")

    repo = Repository(
        github_full_name=data.github_full_name,
        installation_id=data.installation_id,
        default_branch=data.default_branch,
    )
    db.add(repo)
    await db.flush()
    logger.info("repository_created", repo=data.github_full_name)
    return repo


@router.get("", response_model=list[RepositoryResponse])
async def list_repositories(
    db: AsyncSession = Depends(get_db),
) -> list[Repository]:
    result = await db.execute(select(Repository).order_by(Repository.created_at.desc()))
    return list(result.scalars().all())


@router.get("/{repo_full_name:path}", response_model=RepositoryResponse)
async def get_repository(
    repo_full_name: str,
    db: AsyncSession = Depends(get_db),
) -> Repository:
    result = await db.execute(
        select(Repository).where(Repository.github_full_name == repo_full_name)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")
    return repo
