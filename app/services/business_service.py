"""Business profile service."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import MODULE_SETTINGS, AuditAction
from app.core.exceptions import NotFoundError, ValidationError
from app.database.repositories.business_repository import BusinessRepository
from app.schemas.business_schema import BusinessSummary, BusinessUpdateRequest
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.utils.date_utils import utcnow


class BusinessService(BaseService):
    """Read and update the workspace business profile."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        business_repository: BusinessRepository,
        audit_service: AuditService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._business = business_repository
        self._audit = audit_service

    def get_business(self) -> BusinessSummary:
        """Business profile for any signed-in user (used by the dashboard)."""
        with self.unit_of_work(write=False) as db:
            self._current_user(db)
            business = self._business.get_primary(db)
            if business is None:
                raise NotFoundError("The business profile has not been configured yet")
            return BusinessSummary.from_business(business)

    def update_business(self, payload: dict | BusinessUpdateRequest) -> BusinessSummary:
        with self.unit_of_work() as db:
            # Authorise first so an unauthorised caller learns nothing about the payload.
            actor = self._authorize(db, "settings.update")
            data = validate_payload(BusinessUpdateRequest, payload)
            business = self._business.get_primary(db)
            if business is None:
                raise NotFoundError("The business profile has not been configured yet")

            old_values = {
                "business_name": business.business_name,
                "owner_name": business.owner_name,
                "email": business.email,
                "phone": business.phone,
                "address": business.address,
                "currency": business.currency,
                "timezone": business.timezone,
                "financial_year_start": business.financial_year_start,
            }

            business.business_name = data.business_name
            business.owner_name = data.owner_name
            business.email = data.email
            business.phone = data.phone
            business.address = data.address
            business.currency = data.currency
            business.timezone = data.timezone
            business.financial_year_start = data.financial_year_start
            business.updated_at = utcnow()

            new_values = {
                "business_name": business.business_name,
                "owner_name": business.owner_name,
                "email": business.email,
                "phone": business.phone,
                "address": business.address,
                "currency": business.currency,
                "timezone": business.timezone,
                "financial_year_start": business.financial_year_start,
            }
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_BUSINESS_SETTINGS,
                module=MODULE_SETTINGS,
                entity_type="Business",
                entity_id=business.id,
                old_values=old_values,
                new_values=new_values,
            )
            return BusinessSummary.from_business(business)
