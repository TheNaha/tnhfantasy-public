from typing import List, Dict, Any, Optional
from sqlmodel import Session, select
from sqlalchemy import text
from core.entities import Collection, CollectionImage
from collections import defaultdict
from datetime import datetime, timezone

class CollectionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_collections_with_counts(self) -> List[Dict[str, Any]]:
        query = text("""
            SELECT c.*, COUNT(ci.id) as image_count
            FROM collections c
            LEFT JOIN collection_images ci ON c.id = ci.collection_id
            GROUP BY c.id
            ORDER BY c.updated_at DESC
        """)
        result = self.session.execute(query)
        collections = []
        for row in result:
            collections.append(dict(row._mapping))
        return collections

    def get_collection(self, collection_id: int) -> Optional[Collection]:
        return self.session.get(Collection, collection_id)

    def create_collection(self, collection: Collection) -> Collection:
        self.session.add(collection)
        self.session.flush()
        return collection

    def update_collection(self, collection: Collection) -> Collection:
        self.session.add(collection)
        return collection

    def delete_collection(self, collection: Collection):
        self.session.execute(
            text("DELETE FROM collection_images WHERE collection_id = :id"),
            {"id": collection.id}
        )
        self.session.delete(collection)

    def get_collection_images(self, collection_id: int) -> List[CollectionImage]:
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id
        ).order_by(CollectionImage.added_at.desc())
        return self.session.exec(stmt).all()

    def get_collection_image(self, collection_id: int, filename: str) -> Optional[CollectionImage]:
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id,
            CollectionImage.image_filename == filename
        )
        return self.session.exec(stmt).first()

    def add_collection_image(self, collection_image: CollectionImage):
        self.session.add(collection_image)
        self.session.flush()

    def remove_collection_images(self, collection_id: int, filenames: List[str]) -> int:
        removed = 0
        for filename in filenames:
            result = self.session.execute(
                text("""
                    DELETE FROM collection_images 
                    WHERE collection_id = :col_id AND image_filename = :filename
                """),
                {"col_id": collection_id, "filename": filename}
            )
            removed += result.rowcount
        return removed

    def get_latest_collection_image(self, collection_id: int) -> Optional[CollectionImage]:
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id
        ).order_by(CollectionImage.added_at.desc()).limit(1)
        return self.session.exec(stmt).first()

    def get_all_collections(self) -> List[Collection]:
        return self.session.exec(select(Collection)).all()

    def get_images_for_collections(self, collection_ids: List[int]) -> List[CollectionImage]:
        return self.session.exec(
            select(CollectionImage).where(CollectionImage.collection_id.in_(collection_ids))
        ).all()
