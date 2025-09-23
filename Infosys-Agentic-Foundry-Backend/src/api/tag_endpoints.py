# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from fastapi import APIRouter, Depends, HTTPException, Request

from src.schemas import TagData, UpdateTagData, DeleteTagData
from src.database.services import TagService
from src.api.dependencies import ServiceProvider # The dependency provider

from telemetry_wrapper import update_session_context


# Create an APIRouter instance for tag-related endpoints
router = APIRouter(prefix="/tags", tags=["Tags"])


@router.post("/create")
async def create_tag_endpoint(request: Request, tag_data: TagData, tag_service: TagService = Depends(ServiceProvider.get_tag_service)):
    """
    API endpoint to create a new tag.

    Parameters:
    - request: The FastAPI Request object (for context like user_id from cookies).
    - tag_data: Pydantic model containing tag_name and created_by.
    - tag_service: Dependency-injected TagService instance.

    Returns:
    - dict: Status of the tag creation operation.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tag_service.create_tag(tag_name=tag_data.tag_name, created_by=tag_data.created_by)
    if not result.get("is_created"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.get("/get-available-tags", deprecated=True, summary="Deprecated: Use [ /tags/get ] instead")
@router.get("/get")
async def get_all_tags_endpoint(request: Request, tag_service: TagService = Depends(ServiceProvider.get_tag_service)):
    """
    API endpoint to retrieve all tags.

    Parameters:
    - request: The FastAPI Request object.
    - tag_service: Dependency-injected TagService instance.

    Returns:
    - List[Dict[str, Any]]: A list of all tags.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    return await tag_service.get_all_tags()


@router.get("/get/{tag_id}")
async def get_tag_by_id_endpoint(request: Request, tag_id: str, tag_service: TagService = Depends(ServiceProvider.get_tag_service)):
    """
    API endpoint to retrieve a tag by its ID.

    Parameters:
    - request: The FastAPI Request object.
    - tag_id: The ID of the tag to retrieve.
    - tag_service: Dependency-injected TagService instance.

    Returns:
    - Dict[str, Any]: The retrieved tag.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tag_service.get_tag(tag_id=tag_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tag not found")
    return result


@router.put("/update")
async def update_tag_endpoint(request: Request, update_data: UpdateTagData, tag_service: TagService = Depends(ServiceProvider.get_tag_service)):
    """
    API endpoint to update an existing tag.

    Parameters:
    - request: The FastAPI Request object.
    - update_data: Pydantic model containing update details.
    - tag_service: Dependency-injected TagService instance.

    Returns:
    - Dict[str, Any]: Status of the update operation.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tag_service.update_tag(
        new_tag_name=update_data.new_tag_name,
        created_by=update_data.created_by,
        tag_id=update_data.tag_id,
        tag_name=update_data.tag_name
    )
    if not result.get("is_updated"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.delete("/delete")
async def delete_tag_endpoint(request: Request, delete_data: DeleteTagData, tag_service: TagService = Depends(ServiceProvider.get_tag_service)):
    """
    API endpoint to delete a tag.

    Parameters:
    - request: The FastAPI Request object.
    - delete_data: Pydantic model containing deletion criteria.
    - tag_service: Dependency-injected TagService instance.

    Returns:
    - Dict[str, Any]: Status of the deletion operation.
    """
    user_id = request.cookies.get("user_id")
    user_session = request.cookies.get("user_session")
    update_session_context(user_session=user_session, user_id=user_id)

    result = await tag_service.delete_tag(
        created_by=delete_data.created_by,
        tag_id=delete_data.tag_id,
        tag_name=delete_data.tag_name
    )
    if not result.get("is_deleted"):
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result

