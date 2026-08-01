from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from core.entities import Collection, CollectionImage


class CollectionRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_collections_with_counts(self) -> list[dict[str, Any]]:
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

    def get_collection(self, collection_id: int) -> Collection | None:
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

    def get_collection_images(self, collection_id: int) -> list[CollectionImage]:
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id
        ).order_by(CollectionImage.added_at.desc())
        return self.session.exec(stmt).all()

    def get_collection_image(self, collection_id: int, filename: str) -> CollectionImage | None:
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id,
            CollectionImage.image_filename == filename
        )
        return self.session.exec(stmt).first()

    def get_collection_images_by_filenames(self, collection_id: int, filenames: list[str]) -> list[CollectionImage]:
        if not filenames:
            return []
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id,
            CollectionImage.image_filename.in_(filenames)
        )
        return self.session.exec(stmt).all()

    def add_collection_image(self, collection_image: CollectionImage):
        self.session.add(collection_image)
        self.session.flush()

    def add_collection_images(self, collection_images: list[CollectionImage]):
        if not collection_images:
            return
        self.session.add_all(collection_images)
        self.session.flush()

    def remove_collection_images(self, collection_id: int, filenames: list[str]) -> int:
        if not filenames:
            return 0
            
        from sqlalchemy import delete
        stmt = delete(CollectionImage).where(
            CollectionImage.collection_id == collection_id,
            CollectionImage.image_filename.in_(filenames)
        )
        result = self.session.execute(stmt)
        return result.rowcount

    def get_latest_collection_image(self, collection_id: int) -> CollectionImage | None:
        stmt = select(CollectionImage).where(
            CollectionImage.collection_id == collection_id
        ).order_by(CollectionImage.added_at.desc()).limit(1)
        return self.session.exec(stmt).first()

    def get_all_collections(self) -> list[Collection]:
        return self.session.exec(select(Collection)).all()

    def get_images_for_collections(self, collection_ids: list[int]) -> list[CollectionImage]:
        return self.session.exec(
            select(CollectionImage).where(CollectionImage.collection_id.in_(collection_ids))
        ).all()

    def get_collection_by_character_id(self, character_id: str) -> Collection | None:
        stmt = select(Collection).where(Collection.character_id == character_id)
        return self.session.exec(stmt).first()
