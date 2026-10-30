"""Common pagination models for API endpoints."""

from typing import Annotated, Generic, TypeVar

from fastapi import Query
from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginationParams(BaseModel):
    """Query parameters for pagination.
    
    Default page size is 20 items. Maximum varies by endpoint based on response size.
    """
    
    page: Annotated[int, Query(ge=1)] = 1
    page_size: Annotated[int, Query(ge=1, le=200)] = 20


class PageInfo(BaseModel):
    """Pagination metadata."""
    
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total_items: int = Field(ge=0)
    total_pages: int = Field(ge=0)
    has_next: bool
    has_prev: bool


class PaginatedResponse(BaseModel, Generic[T]):  # noqa: UP046
    """Generic paginated response wrapper.
    
    Contains the data items and pagination metadata.
    """
    
    items: list[T]
    page_info: PageInfo

    @classmethod
    def create(
        cls,
        items: list[T],
        total: int,
        page: int,
        page_size: int,
    ) -> "PaginatedResponse[T]":
        """Factory method to create a paginated response.
        
        Args:
            items: List of items for the current page
            total: Total number of items across all pages
            page: Current page number (1-indexed)
            page_size: Number of items per page
            
        Returns:
            PaginatedResponse with items and computed page info
        """
        total_pages = (total + page_size - 1) // page_size if page_size > 0 else 0
        
        return cls(
            items=items,
            page_info=PageInfo(
                page=page,
                page_size=page_size,
                total_items=total,
                total_pages=total_pages,
                has_next=page < total_pages,
                has_prev=page > 1,
            ),
        )
