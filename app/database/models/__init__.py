"""ORM model registry.

Importing this package registers every model on the shared metadata, which is
required before mappers are configured or migrations are generated.
"""

from app.database.models.ai import (
    AIConversation,
    AIMessage,
    AIModelSetting,
    AIToolRegistryEntry,
    AIWorkflow,
    AIWorkflowStep,
)
from app.database.models.agents import (
    Agent,
    AgentExecution,
    AgentFinding,
    AgentMemory,
    AgentRecommendation,
)
from app.database.models.analytics import (
    AnalyticsReportHistory,
    AnalyticsSnapshot,
    AnomalyReview,
    BusinessKPI,
    BusinessRiskAssessment,
    BusinessSimulation,
    DetectedAnomaly,
    ForecastModelMetric,
    ForecastRun,
    ForecastValue,
    SimulationResult,
)
from app.database.models.security import (
    AgentSecurityPolicy,
    AIDataGovernancePolicy,
    AuditIntegrityRecord,
    BackupHistory,
    MfaRecoveryCode,
    ResourceAccessPolicy,
    SecurityEvent,
    SecurityIncidentReview,
    SecurityPolicy,
    SessionSecurityRecord,
    UserMfaSetting,
)
from app.database.models.knowledge import (
    DocumentChunk,
    DocumentEntity,
    DocumentExtractionResult,
    EmbeddingModelRegistry,
    HybridAIUsage,
    KnowledgeAccessPolicy,
    KnowledgeCollection,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeProcessingJob,
    KnowledgeSearchHistory,
    RagQueryHistory,
    RagSourceReference,
)
from app.database.models.autonomy import (
    ApprovalDecision,
    ApprovalRequest,
    AutonomyPolicy,
    AutonomousWorkflow,
    ScheduledWorkflow,
    WorkflowDeadLetter,
    WorkflowExecutionLog,
    WorkflowIdempotencyRecord,
    WorkflowTask,
    WorkflowTrigger,
)
from app.database.models.collaboration import (
    AgentCollaboration,
    CollaborationCheckpoint,
    CollaborationConflict,
    CollaborationDecision,
    CollaborationDependency,
    CollaborationFinding,
    CollaborationMessage,
    CollaborationTask,
)
from app.database.models.audit_log import AuditLog
from app.database.models.business import Business
from app.database.models.catalog import Category, Product
from app.database.models.crm import Customer, CustomerFollowUp
from app.database.models.events import BusinessEvent
from app.database.models.finance import Expense, FinancialTransaction
from app.database.models.inventory import Branch, Inventory, StockMovement
from app.database.models.permission import Permission
from app.database.models.purchasing import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.database.models.role import Role
from app.database.models.role_permission import RolePermission
from app.database.models.sales import Invoice, Payment, SalesOrder, SalesOrderItem
from app.database.models.session import UserSession
from app.database.models.user import User
from app.database.models.user_role import UserRole

__all__ = [
    "AIConversation",
    "AnalyticsReportHistory",
    "AgentSecurityPolicy",
    "AIDataGovernancePolicy",
    "AnalyticsSnapshot",
    "AuditIntegrityRecord",
    "BackupHistory",
    "MfaRecoveryCode",
    "ResourceAccessPolicy",
    "SecurityEvent",
    "SecurityIncidentReview",
    "SecurityPolicy",
    "SessionSecurityRecord",
    "UserMfaSetting",
    "DocumentChunk",
    "DocumentEntity",
    "DocumentExtractionResult",
    "EmbeddingModelRegistry",
    "HybridAIUsage",
    "KnowledgeAccessPolicy",
    "KnowledgeCollection",
    "KnowledgeDocument",
    "KnowledgeDocumentVersion",
    "KnowledgeProcessingJob",
    "KnowledgeSearchHistory",
    "RagQueryHistory",
    "RagSourceReference",
    "AnomalyReview",
    "BusinessKPI",
    "BusinessRiskAssessment",
    "BusinessSimulation",
    "DetectedAnomaly",
    "ForecastModelMetric",
    "ForecastRun",
    "ForecastValue",
    "SimulationResult",
    "ApprovalDecision",
    "ApprovalRequest",
    "AutonomousWorkflow",
    "AutonomyPolicy",
    "ScheduledWorkflow",
    "WorkflowDeadLetter",
    "WorkflowExecutionLog",
    "WorkflowIdempotencyRecord",
    "WorkflowTask",
    "WorkflowTrigger",
    "AgentCollaboration",
    "CollaborationCheckpoint",
    "CollaborationConflict",
    "CollaborationDecision",
    "CollaborationDependency",
    "CollaborationFinding",
    "CollaborationMessage",
    "CollaborationTask",
    "Agent",
    "AgentExecution",
    "AgentFinding",
    "AgentMemory",
    "AgentRecommendation",
    "AIMessage",
    "AIModelSetting",
    "AIToolRegistryEntry",
    "AIWorkflow",
    "AIWorkflowStep",
    "AuditLog",
    "Branch",
    "Business",
    "BusinessEvent",
    "Category",
    "Customer",
    "CustomerFollowUp",
    "Expense",
    "FinancialTransaction",
    "GoodsReceipt",
    "GoodsReceiptItem",
    "Inventory",
    "Invoice",
    "Payment",
    "Permission",
    "Product",
    "PurchaseOrder",
    "PurchaseOrderItem",
    "Role",
    "RolePermission",
    "SalesOrder",
    "SalesOrderItem",
    "StockMovement",
    "Supplier",
    "User",
    "UserRole",
    "UserSession",
]
