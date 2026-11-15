"""Application composition root.

Constructs the database, repositories, security components and services once
and hands them to the UI. Explicit constructor injection is used throughout so
every dependency can be replaced in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.ai.events.event_processor import EventProcessor
from app.ai.orchestrator.orchestrator import BizPilotOrchestrator, OrchestratorConfig
from app.ai.orchestrator.workflow_executor import WorkflowExecutor
from app.ai.agents.business_intelligence_agent import BusinessIntelligenceAgent
from app.ai.providers.hybrid_ai_router import HybridAIModelRouter
from app.security.audit.audit_integrity import AuditIntegrityService
from app.security.authz.authorization_service import AuthorizationService
from app.security.backup.secure_backup import SecureBackupService
from app.security.data_protection.secret_manager import SecretManager
from app.security.file_security import FileSecurityService
from app.security.governance.ai_agent_security import AIAgentSecurityPolicyService
from app.security.governance.ai_data_governance import AIDataGovernanceService
from app.security.governance.approval_governance import ApprovalGovernanceService
from app.security.mfa.mfa_service import MfaService
from app.security.monitoring.security_monitor import SecurityMonitoringService
from app.analytics.analytics_engine import BusinessAnalyticsEngine
from app.document_intelligence.document_chunker import DocumentChunker
from app.document_intelligence.document_extractor import (
    DocumentClassifier,
    DocumentIntelligenceService,
)
from app.document_intelligence.document_parser import DocumentParser
from app.document_intelligence.ocr_service import OcrService
from app.embeddings.embedding_service import EmbeddingService
from app.knowledge.knowledge_lifecycle import KnowledgeLifecycleService
from app.knowledge.knowledge_manager import BusinessKnowledgeManager
from app.knowledge.knowledge_permissions import KnowledgePermissionService
from app.knowledge_graph.business_knowledge_graph import (
    BusinessKnowledgeGraph,
    EntityResolutionService,
)
from app.rag.rag_pipeline import RagPipeline
from app.vector_store.vector_store_service import LocalVectorStore
from app.ai.autonomy.approvals import ApprovalService
from app.ai.autonomy.engine import AutonomousWorkflowEngine
from app.ai.autonomy.policy_engine import AutonomyPolicyEngine
from app.ai.autonomy.scheduler import WorkflowScheduler
from app.ai.autonomy.triggers import WorkflowTriggerManager
from app.ai.collaboration.manager import MultiAgentCollaborationManager
from app.ai.agents.coordinator import AgentCoordinator
from app.ai.agents.customer_agent import CustomerAgent
from app.ai.agents.finance_agent import FinanceAgent
from app.ai.agents.inventory_agent import InventoryAgent
from app.ai.agents.sales_agent import SalesAgent
from app.ai.memory.business_memory import BusinessMemory
from app.ai.registry.agent_registry import build_agent_registry
from app.ai.registry.tool_catalogue import build_tool_registry
from app.ai.registry.tool_registry import ToolRegistry
from app.ai.routing.credentials import CredentialStore
from app.ai.routing.model_router import ModelRouter
from app.core.config import AppConfig
from app.core.database import Database
from app.core.logging_config import get_logger
from app.database.repositories.ai_repository import AIRepository
from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.business_repository import BusinessRepository
from app.database.repositories.catalog_repository import CatalogRepository
from app.database.repositories.crm_repository import CrmRepository
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.finance_repository import FinanceRepository
from app.database.repositories.inventory_repository import InventoryRepository
from app.database.repositories.permission_repository import PermissionRepository
from app.database.repositories.role_repository import RoleRepository
from app.database.repositories.sales_repository import SalesRepository
from app.database.repositories.session_repository import SessionRepository
from app.database.repositories.supply_repository import SupplyRepository
from app.database.repositories.user_repository import UserRepository
from app.database.seed import ensure_reference_data
from app.security.authentication import Authenticator
from app.security.password_manager import PasswordManager
from app.security.session_manager import SessionManager
from app.security.validators import PasswordPolicy
from app.services.agent_management_service import AgentManagementService
from app.services.analytics_service import AnalyticsService
from app.services.knowledge_service import KnowledgeService
from app.services.security_service import SecurityService
from app.services.autonomy_service import AutonomyService
from app.services.collaboration_service import CollaborationService
from app.services.ai_orchestration_service import AIOrchestrationService
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.backup_service import BackupService
from app.services.base_service import AuthContext
from app.services.business_service import BusinessService
from app.services.customer_service import CustomerService
from app.services.dashboard_service import DashboardService
from app.services.event_service import EventService
from app.services.export_service import ExportService
from app.services.finance_service import FinanceService
from app.services.inventory_service import InventoryService
from app.services.permission_service import PermissionService
from app.services.purchasing_service import PurchasingService
from app.services.role_service import RoleService
from app.services.sales_service import SalesService
from app.services.user_service import UserService

logger = get_logger("application")


@dataclass
class ApplicationContext:
    """Container for every long-lived application dependency."""

    config: AppConfig
    database: Database
    auth_context: AuthContext
    # repositories
    user_repository: UserRepository
    role_repository: RoleRepository
    permission_repository: PermissionRepository
    business_repository: BusinessRepository
    audit_repository: AuditRepository
    session_repository: SessionRepository
    catalog_repository: CatalogRepository
    inventory_repository: InventoryRepository
    crm_repository: CrmRepository
    sales_repository: SalesRepository
    finance_repository: FinanceRepository
    supply_repository: SupplyRepository
    event_repository: EventRepository
    # security
    password_manager: PasswordManager
    password_policy: PasswordPolicy
    session_manager: SessionManager
    authenticator: Authenticator
    # services
    audit_service: AuditService
    event_service: EventService
    export_service: ExportService
    auth_service: AuthService
    user_service: UserService
    role_service: RoleService
    permission_service: PermissionService
    business_service: BusinessService
    dashboard_service: DashboardService
    backup_service: BackupService
    inventory_service: InventoryService
    customer_service: CustomerService
    finance_service: FinanceService
    sales_service: SalesService
    purchasing_service: PurchasingService
    # AI orchestration (Phase 3)
    ai_repository: AIRepository | None = None
    tool_registry: ToolRegistry | None = None
    agent_registry: object | None = None
    model_router: ModelRouter | None = None
    credentials: CredentialStore | None = None
    orchestrator: BizPilotOrchestrator | None = None
    event_processor: EventProcessor | None = None
    ai_service: AIOrchestrationService | None = None
    agent_coordinator: AgentCoordinator | None = None
    agent_manager: AgentManagementService | None = None
    collaboration_manager: MultiAgentCollaborationManager | None = None
    collaboration_service: Any | None = None
    policy_engine: Any | None = None
    workflow_engine: Any | None = None
    approval_service: Any | None = None
    trigger_manager: Any | None = None
    workflow_scheduler: Any | None = None
    autonomy_service: Any | None = None
    analytics_engine: Any | None = None
    analytics_service: Any | None = None
    hybrid_router: Any | None = None
    embedding_service: Any | None = None
    vector_store: Any | None = None
    knowledge_manager: Any | None = None
    rag_pipeline: Any | None = None
    knowledge_service: Any | None = None
    ocr_service: Any | None = None
    authorization_service: Any | None = None
    mfa_service: Any | None = None
    agent_security: Any | None = None
    data_governance: Any | None = None
    approval_governance: Any | None = None
    security_monitor: Any | None = None
    audit_integrity: Any | None = None
    secure_backup: Any | None = None
    file_security: Any | None = None
    security_service: Any | None = None
    business_memory: BusinessMemory | None = None

    @property
    def session_factory(self) -> Callable[[], Session]:
        return self.database.session_factory

    def seed_reference_data(self) -> None:
        """Ensure permissions, system roles and the default branch exist."""
        with self.database.session_factory() as db:
            ensure_reference_data(db)
            db.commit()

    @classmethod
    def build(cls, config: AppConfig, database: Database | None = None) -> "ApplicationContext":
        """Wire the whole application graph."""
        database = database or Database(config)
        if not database.is_initialized:
            database.initialize()
        config.ensure_directories()

        session_factory = database.session_factory
        auth_context = AuthContext()

        # -- repositories --------------------------------------------------
        user_repository = UserRepository()
        role_repository = RoleRepository()
        permission_repository = PermissionRepository()
        business_repository = BusinessRepository()
        audit_repository = AuditRepository()
        session_repository = SessionRepository()
        catalog_repository = CatalogRepository()
        inventory_repository = InventoryRepository()
        crm_repository = CrmRepository()
        sales_repository = SalesRepository()
        finance_repository = FinanceRepository()
        supply_repository = SupplyRepository()
        event_repository = EventRepository()

        # -- security ------------------------------------------------------
        password_manager = PasswordManager()
        password_policy = PasswordPolicy(config.security.min_password_length)
        session_manager = SessionManager(session_repository, config.security)
        authenticator = Authenticator(user_repository, password_manager, config.security)

        # -- cross-cutting services ---------------------------------------
        audit_service = AuditService(
            session_factory, auth_context, audit_repository, user_repository
        )
        event_service = EventService(session_factory, auth_context, event_repository)
        export_service = ExportService(config)

        # -- domain services (Phase 1) ------------------------------------
        auth_service = AuthService(
            session_factory,
            auth_context,
            user_repository=user_repository,
            role_repository=role_repository,
            business_repository=business_repository,
            permission_repository=permission_repository,
            session_repository=session_repository,
            authenticator=authenticator,
            session_manager=session_manager,
            password_manager=password_manager,
            password_policy=password_policy,
            audit_service=audit_service,
            security_settings=config.security,
        )
        user_service = UserService(
            session_factory,
            auth_context,
            user_repository=user_repository,
            role_repository=role_repository,
            session_repository=session_repository,
            password_manager=password_manager,
            password_policy=password_policy,
            session_manager=session_manager,
            authenticator=authenticator,
            audit_service=audit_service,
        )
        role_service = RoleService(
            session_factory,
            auth_context,
            role_repository=role_repository,
            permission_repository=permission_repository,
            user_repository=user_repository,
            audit_service=audit_service,
        )
        permission_service = PermissionService(
            session_factory,
            auth_context,
            permission_repository=permission_repository,
        )
        business_service = BusinessService(
            session_factory,
            auth_context,
            business_repository=business_repository,
            audit_service=audit_service,
        )

        # -- domain services (Phase 2) ------------------------------------
        inventory_service = InventoryService(
            session_factory,
            auth_context,
            catalog_repository=catalog_repository,
            inventory_repository=inventory_repository,
            audit_service=audit_service,
            event_service=event_service,
            export_service=export_service,
        )
        finance_service = FinanceService(
            session_factory,
            auth_context,
            finance_repository=finance_repository,
            sales_repository=sales_repository,
            audit_service=audit_service,
            event_service=event_service,
            export_service=export_service,
        )
        sales_service = SalesService(
            session_factory,
            auth_context,
            sales_repository=sales_repository,
            catalog_repository=catalog_repository,
            crm_repository=crm_repository,
            inventory_repository=inventory_repository,
            inventory_service=inventory_service,
            finance_service=finance_service,
            audit_service=audit_service,
            event_service=event_service,
            export_service=export_service,
        )
        customer_service = CustomerService(
            session_factory,
            auth_context,
            crm_repository=crm_repository,
            sales_repository=sales_repository,
            user_repository=user_repository,
            audit_service=audit_service,
            event_service=event_service,
            export_service=export_service,
        )
        purchasing_service = PurchasingService(
            session_factory,
            auth_context,
            supply_repository=supply_repository,
            catalog_repository=catalog_repository,
            inventory_repository=inventory_repository,
            inventory_service=inventory_service,
            audit_service=audit_service,
            event_service=event_service,
        )

        dashboard_service = DashboardService(
            session_factory,
            auth_context,
            user_repository=user_repository,
            role_repository=role_repository,
            business_repository=business_repository,
            audit_service=audit_service,
            sales_repository=sales_repository,
            finance_repository=finance_repository,
            crm_repository=crm_repository,
            inventory_repository=inventory_repository,
            catalog_repository=catalog_repository,
            connection_check=database.check_connection,
            schema_version=database.schema_version,
        )
        backup_service = BackupService(
            session_factory,
            auth_context,
            database=database,
            audit_service=audit_service,
        )

        context = cls(
            config=config,
            database=database,
            auth_context=auth_context,
            user_repository=user_repository,
            role_repository=role_repository,
            permission_repository=permission_repository,
            business_repository=business_repository,
            audit_repository=audit_repository,
            session_repository=session_repository,
            catalog_repository=catalog_repository,
            inventory_repository=inventory_repository,
            crm_repository=crm_repository,
            sales_repository=sales_repository,
            finance_repository=finance_repository,
            supply_repository=supply_repository,
            event_repository=event_repository,
            password_manager=password_manager,
            password_policy=password_policy,
            session_manager=session_manager,
            authenticator=authenticator,
            audit_service=audit_service,
            event_service=event_service,
            export_service=export_service,
            auth_service=auth_service,
            user_service=user_service,
            role_service=role_service,
            permission_service=permission_service,
            business_service=business_service,
            dashboard_service=dashboard_service,
            backup_service=backup_service,
            inventory_service=inventory_service,
            customer_service=customer_service,
            finance_service=finance_service,
            sales_service=sales_service,
            purchasing_service=purchasing_service,
        )
        context.seed_reference_data()
        # Deliver any events left pending by a previous session.
        event_service.dispatch_pending()
        context._build_ai_layer(config)
        logger.info("Application context ready")
        return context

    def _build_ai_layer(self, config: AppConfig) -> None:
        """Wire the Phase 3 orchestration layer onto the existing services."""
        self.ai_repository = AIRepository()
        self.tool_registry = build_tool_registry()
        self.agent_registry = build_agent_registry()
        self.credentials = CredentialStore()
        self.model_router = ModelRouter(credentials=self.credentials)
        checkpoint_path = config.data_dir / "ai_checkpoints.sqlite"

        executor = WorkflowExecutor(
            session_factory=self.database.session_factory,
            registry=self.tool_registry,
            checkpoint_path=checkpoint_path,
            services=self,
            max_seconds=180.0,
        )
        self.orchestrator = BizPilotOrchestrator(
            session_factory=self.database.session_factory,
            services=self,
            registry=self.tool_registry,
            agents=self.agent_registry,
            router=self.model_router,
            executor=executor,
            audit_service=self.audit_service,
            checkpoint_path=checkpoint_path,
            config=OrchestratorConfig(),
        )
        # ---- Phase 4: specialist agents -------------------------------
        coordinator = AgentCoordinator(max_depth=1)
        coordinator.register(FinanceAgent())
        coordinator.register(SalesAgent())
        coordinator.register(CustomerAgent())
        coordinator.register(InventoryAgent())
        coordinator.register(
            BusinessIntelligenceAgent(coordinator_provider=lambda: coordinator)
        )
        self.agent_coordinator = coordinator
        self.business_memory = BusinessMemory(self.database.session_factory)

        self.agent_manager = AgentManagementService(
            self.database.session_factory,
            self.auth_context,
            coordinator=coordinator,
            memory=self.business_memory,
            audit_service=self.audit_service,
            registry=self.tool_registry,
            orchestrator=self.orchestrator,
            services=self,
        )

        self.collaboration_manager = MultiAgentCollaborationManager(
            session_factory=self.database.session_factory,
            agent_manager=self.agent_manager,
            tool_runner_factory=self.agent_manager.make_tool_runner,
            known_sources=set(self.tool_registry.names()),
            audit_service=self.audit_service,
        )

        self.collaboration_service = CollaborationService(
            self.database.session_factory,
            self.auth_context,
            manager=self.collaboration_manager,
            export_service=self.export_service,
            audit_service=self.audit_service,
            services=self,
        )

        # ---- Phase 6: autonomous workflows ----------------------------------
        self.policy_engine = AutonomyPolicyEngine(self.database.session_factory)
        self.workflow_engine = AutonomousWorkflowEngine(
            session_factory=self.database.session_factory,
            services=self,
            policy_engine=self.policy_engine,
            audit_service=self.audit_service,
            agent_manager=self.agent_manager,
            collaboration_manager=self.collaboration_manager,
        )
        self.approval_service = ApprovalService(
            self.database.session_factory,
            self.auth_context,
            policy_engine=self.policy_engine,
            services=self,
            audit_service=self.audit_service,
            on_approved=self.workflow_engine.on_approval_granted,
        )
        self.workflow_engine.attach_approvals(self.approval_service)
        self.trigger_manager = WorkflowTriggerManager(
            session_factory=self.database.session_factory, engine=self.workflow_engine
        )
        self.workflow_scheduler = WorkflowScheduler(
            session_factory=self.database.session_factory, engine=self.workflow_engine
        )
        self.autonomy_service = AutonomyService(
            self.database.session_factory,
            self.auth_context,
            engine=self.workflow_engine,
            policy_engine=self.policy_engine,
            approvals=self.approval_service,
            scheduler=self.workflow_scheduler,
            triggers=self.trigger_manager,
            audit_service=self.audit_service,
        )

        # ---- Phase 7: business intelligence --------------------------------
        self.analytics_engine = BusinessAnalyticsEngine(self)
        self.analytics_service = AnalyticsService(
            self.database.session_factory,
            self.auth_context,
            engine=self.analytics_engine,
            audit_service=self.audit_service,
            export_service=self.export_service,
        )

        # ---- Phase 8: hybrid AI and business knowledge ---------------------
        self.hybrid_router = HybridAIModelRouter(
            self.model_router,
            session_factory=self.database.session_factory,
            policy=self.config.routing_policy if hasattr(self.config, "routing_policy") else "LOCAL_FIRST",
            offline_mode=not getattr(self.config, "cloud_sharing_enabled", False),
        )
        self.ocr_service = OcrService()
        self.embedding_service = EmbeddingService(self.database.session_factory)
        self.embedding_service.ensure_registered()
        knowledge_dir = self.config.document_dir
        self.vector_store = LocalVectorStore(
            self.config.vector_dir / "vectors.db",
            dimension=self.embedding_service.dimension,
            model_id=self.embedding_service.model_id,
        )
        self.knowledge_permissions = KnowledgePermissionService()
        self.knowledge_lifecycle = KnowledgeLifecycleService()
        self.knowledge_manager = BusinessKnowledgeManager(
            session_factory=self.database.session_factory,
            storage_root=knowledge_dir,
            vector_store=self.vector_store,
            embedding_service=self.embedding_service,
            parser=DocumentParser(self.ocr_service),
            chunker=DocumentChunker(),
            classifier=DocumentClassifier(),
            intelligence=DocumentIntelligenceService(),
            permissions=self.knowledge_permissions,
            lifecycle=self.knowledge_lifecycle,
            entity_resolver=EntityResolutionService(self),
        )
        self.rag_pipeline = RagPipeline(
            knowledge_manager=self.knowledge_manager,
            hybrid_router=self.hybrid_router,
            services=self,
            session_factory=self.database.session_factory,
        )
        self.knowledge_service = KnowledgeService(
            self.database.session_factory,
            self.auth_context,
            manager=self.knowledge_manager,
            permissions=self.knowledge_permissions,
            rag=self.rag_pipeline,
            graph=BusinessKnowledgeGraph(self),
            hybrid_router=self.hybrid_router,
            audit_service=self.audit_service,
            storage_root=knowledge_dir,
        )

        # ---- Phase 9: security and governance ------------------------------
        self.secret_manager = SecretManager(self.config.data_dir / "secrets" / "app.key")
        self.authorization_service = AuthorizationService()
        self.file_security = FileSecurityService()
        self.mfa_service = MfaService(
            self.database.session_factory, self.secret_manager
        )
        self.agent_security = AIAgentSecurityPolicyService(self.database.session_factory)
        self.data_governance = AIDataGovernanceService(
            self.database.session_factory, self.secret_manager
        )
        self.approval_governance = ApprovalGovernanceService()
        self.security_monitor = SecurityMonitoringService(self.database.session_factory)
        self.audit_integrity = AuditIntegrityService(self.database.session_factory)
        self.secure_backup = SecureBackupService(
            self.database.session_factory,
            self.backup_service,
            knowledge_root=self.config.document_dir,
        )
        # Phase 9 enforcement hooks into the existing components.
        self.audit_service.attach_integrity(self.audit_integrity)
        self.agent_manager.attach_agent_security(self.agent_security)
        self.hybrid_router.attach_governance(self.data_governance, redactor=self.secret_manager)
        self.approval_service._governance = self.approval_governance  # noqa: SLF001

        self.security_service = SecurityService(
            self.database.session_factory,
            self.auth_context,
            authorization=self.authorization_service,
            mfa=self.mfa_service,
            agent_policies=self.agent_security,
            data_governance=self.data_governance,
            approvals=self.approval_governance,
            monitor=self.security_monitor,
            backups=self.secure_backup,
            audit_service=self.audit_service,
            audit_integrity=self.audit_integrity,
        )

        self.event_processor = EventProcessor(self.orchestrator)
        self.ai_service = AIOrchestrationService(
            self.database.session_factory,
            self.auth_context,
            orchestrator=self.orchestrator,
            router=self.model_router,
            registry=self.tool_registry,
            agents=self.agent_registry,
            ai_repository=self.ai_repository,
            audit_service=self.audit_service,
            event_processor=self.event_processor,
        )
        try:
            self.ai_service.sync_registries()
            self.agent_manager.sync_agents()
            self.collaboration_manager.recover_interrupted()
            self.policy_engine.seed_defaults()
            self.workflow_scheduler.seed_defaults()
            self.workflow_engine.recover_interrupted()
            self.approval_service.expire_stale()
            self.agent_security.seed_defaults()
            self.data_governance.seed_defaults()
            self.audit_integrity.backfill()
            self.orchestrator.recover()
        except Exception:  # pragma: no cover - never block startup on AI setup
            logger.exception("AI layer initialisation problem")
        logger.info("AI orchestration layer ready")
