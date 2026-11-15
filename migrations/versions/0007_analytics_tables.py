"""Phase 7: analytics, anomaly, forecast, risk and simulation tables

Revision ID: 0007_analytics
Revises: 0006_autonomy
Create Date: 2026-11-04 06:39:16.980698

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0007_analytics'
down_revision = '0006_autonomy'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('analytics_snapshots',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('snapshot_key', sa.String(length=120), nullable=False),
    sa.Column('snapshot_type', sa.String(length=40), nullable=False),
    sa.Column('period_start', sa.DateTime(), nullable=True),
    sa.Column('period_end', sa.DateTime(), nullable=True),
    sa.Column('granularity', sa.String(length=20), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('data_points', sa.Integer(), nullable=False),
    sa.Column('completeness', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analytics_snapshots')),
    sa.UniqueConstraint('snapshot_key', name='uq_analytics_snapshots_key')
    )
    with op.batch_alter_table('analytics_snapshots', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_analytics_snapshots_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_analytics_snapshots_period_end'), ['period_end'], unique=False)
        batch_op.create_index(batch_op.f('ix_analytics_snapshots_period_start'), ['period_start'], unique=False)
        batch_op.create_index(batch_op.f('ix_analytics_snapshots_snapshot_key'), ['snapshot_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_analytics_snapshots_snapshot_type'), ['snapshot_type'], unique=False)

    op.create_table('business_kpis',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('kpi_key', sa.String(length=80), nullable=False),
    sa.Column('kpi_name', sa.String(length=120), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('formula', sa.Text(), nullable=False),
    sa.Column('period_label', sa.String(length=40), nullable=False),
    sa.Column('period_start', sa.DateTime(), nullable=True),
    sa.Column('period_end', sa.DateTime(), nullable=True),
    sa.Column('actual_value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('comparison_value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.Column('data_completeness', sa.String(length=20), nullable=False),
    sa.Column('source_records', sa.JSON(), nullable=True),
    sa.Column('limitation', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_kpis')),
    sa.UniqueConstraint('kpi_key', name='uq_business_kpis_key')
    )
    with op.batch_alter_table('business_kpis', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_business_kpis_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_kpis_kpi_key'), ['kpi_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_kpis_updated_at'), ['updated_at'], unique=False)

    op.create_table('business_risk_assessments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('risk_key', sa.String(length=60), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('likelihood', sa.String(length=20), nullable=False),
    sa.Column('impact', sa.String(length=20), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('score', sa.Numeric(precision=6, scale=2), nullable=True),
    sa.Column('formula', sa.Text(), nullable=False),
    sa.Column('mitigation', sa.Text(), nullable=False),
    sa.Column('data_limitations', sa.Text(), nullable=True),
    sa.Column('assessed_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_risk_assessments')),
    sa.UniqueConstraint('risk_key', name='uq_business_risk_assessments_key')
    )
    with op.batch_alter_table('business_risk_assessments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_business_risk_assessments_assessed_at'), ['assessed_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_risk_assessments_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_risk_assessments_risk_key'), ['risk_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_risk_assessments_severity'), ['severity'], unique=False)

    op.create_table('detected_anomalies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('anomaly_id', sa.String(length=40), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('anomaly_type', sa.String(length=60), nullable=False),
    sa.Column('affected_record', sa.String(length=120), nullable=False),
    sa.Column('affected_record_id', sa.Integer(), nullable=True),
    sa.Column('detection_method', sa.String(length=60), nullable=False),
    sa.Column('observed_value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('expected_value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('deviation', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('explanation', sa.Text(), nullable=False),
    sa.Column('detected_at', sa.DateTime(), nullable=False),
    sa.Column('review_status', sa.String(length=20), server_default=sa.text("'NEW'"), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_detected_anomalies')),
    sa.UniqueConstraint('anomaly_id', name='uq_detected_anomalies_key')
    )
    with op.batch_alter_table('detected_anomalies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_detected_anomalies_anomaly_id'), ['anomaly_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_detected_anomalies_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_detected_anomalies_detected_at'), ['detected_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_detected_anomalies_review_status'), ['review_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_detected_anomalies_severity'), ['severity'], unique=False)

    op.create_table('forecast_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('run_ref', sa.String(length=40), nullable=False),
    sa.Column('target', sa.String(length=40), nullable=False),
    sa.Column('metric', sa.String(length=60), nullable=False),
    sa.Column('method', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=30), nullable=False),
    sa.Column('data_points', sa.Integer(), nullable=False),
    sa.Column('horizon', sa.Integer(), nullable=False),
    sa.Column('train_start', sa.DateTime(), nullable=True),
    sa.Column('train_end', sa.DateTime(), nullable=True),
    sa.Column('validation_start', sa.DateTime(), nullable=True),
    sa.Column('validation_end', sa.DateTime(), nullable=True),
    sa.Column('model_version', sa.String(length=40), nullable=False),
    sa.Column('trained_at', sa.DateTime(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('insufficient_reason', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_forecast_runs')),
    sa.UniqueConstraint('run_ref', name='uq_forecast_runs_ref')
    )
    with op.batch_alter_table('forecast_runs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_forecast_runs_run_ref'), ['run_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_runs_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_runs_target'), ['target'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_runs_trained_at'), ['trained_at'], unique=False)

    op.create_table('analytics_report_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('report_ref', sa.String(length=40), nullable=False),
    sa.Column('report_type', sa.String(length=60), nullable=False),
    sa.Column('period_label', sa.String(length=40), nullable=False),
    sa.Column('period_start', sa.DateTime(), nullable=True),
    sa.Column('period_end', sa.DateTime(), nullable=True),
    sa.Column('file_format', sa.String(length=10), nullable=False),
    sa.Column('file_name', sa.String(length=160), nullable=False),
    sa.Column('generated_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['generated_by'], ['users.id'], name=op.f('fk_analytics_report_history_generated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analytics_report_history'))
    )
    with op.batch_alter_table('analytics_report_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_analytics_report_history_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_analytics_report_history_report_ref'), ['report_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_analytics_report_history_report_type'), ['report_type'], unique=False)

    op.create_table('anomaly_reviews',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('anomaly_id', sa.String(length=40), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_anomaly_reviews_reviewed_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_anomaly_reviews'))
    )
    with op.batch_alter_table('anomaly_reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_anomaly_reviews_anomaly_id'), ['anomaly_id'], unique=False)

    op.create_table('business_simulations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('simulation_ref', sa.String(length=40), nullable=False),
    sa.Column('scenario_type', sa.String(length=40), nullable=False),
    sa.Column('parameters', sa.JSON(), nullable=True),
    sa.Column('baseline', sa.JSON(), nullable=True),
    sa.Column('assumptions', sa.JSON(), nullable=True),
    sa.Column('limitations', sa.JSON(), nullable=True),
    sa.Column('label', sa.String(length=60), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_business_simulations_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_business_simulations')),
    sa.UniqueConstraint('simulation_ref', name='uq_business_simulations_ref')
    )
    with op.batch_alter_table('business_simulations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_business_simulations_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_simulations_scenario_type'), ['scenario_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_business_simulations_simulation_ref'), ['simulation_ref'], unique=False)

    op.create_table('forecast_model_metrics',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('metric_name', sa.String(length=20), nullable=False),
    sa.Column('value', sa.Float(), nullable=True),
    sa.Column('note', sa.String(length=160), nullable=True),
    sa.ForeignKeyConstraint(['run_id'], ['forecast_runs.id'], name=op.f('fk_forecast_model_metrics_run_id_forecast_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_forecast_model_metrics'))
    )
    with op.batch_alter_table('forecast_model_metrics', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_forecast_model_metrics_run_id'), ['run_id'], unique=False)

    op.create_table('forecast_values',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('run_id', sa.Integer(), nullable=False),
    sa.Column('period_label', sa.String(length=20), nullable=False),
    sa.Column('period_start', sa.DateTime(), nullable=True),
    sa.Column('value', sa.Numeric(precision=18, scale=4), nullable=False),
    sa.Column('lower_bound', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('upper_bound', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('is_forecast', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['run_id'], ['forecast_runs.id'], name=op.f('fk_forecast_values_run_id_forecast_runs'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_forecast_values'))
    )
    with op.batch_alter_table('forecast_values', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_forecast_values_period_start'), ['period_start'], unique=False)
        batch_op.create_index(batch_op.f('ix_forecast_values_run_id'), ['run_id'], unique=False)

    op.create_table('simulation_results',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('simulation_id', sa.Integer(), nullable=False),
    sa.Column('metric', sa.String(length=60), nullable=False),
    sa.Column('baseline_value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('simulated_value', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('delta', sa.Numeric(precision=18, scale=4), nullable=True),
    sa.Column('delta_percent', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('unit', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['simulation_id'], ['business_simulations.id'], name=op.f('fk_simulation_results_simulation_id_business_simulations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_simulation_results'))
    )
    with op.batch_alter_table('simulation_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_simulation_results_simulation_id'), ['simulation_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('simulation_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_simulation_results_simulation_id'))

    op.drop_table('simulation_results')
    with op.batch_alter_table('forecast_values', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_forecast_values_run_id'))
        batch_op.drop_index(batch_op.f('ix_forecast_values_period_start'))

    op.drop_table('forecast_values')
    with op.batch_alter_table('forecast_model_metrics', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_forecast_model_metrics_run_id'))

    op.drop_table('forecast_model_metrics')
    with op.batch_alter_table('business_simulations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_business_simulations_simulation_ref'))
        batch_op.drop_index(batch_op.f('ix_business_simulations_scenario_type'))
        batch_op.drop_index(batch_op.f('ix_business_simulations_created_at'))

    op.drop_table('business_simulations')
    with op.batch_alter_table('anomaly_reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_anomaly_reviews_anomaly_id'))

    op.drop_table('anomaly_reviews')
    with op.batch_alter_table('analytics_report_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_analytics_report_history_report_type'))
        batch_op.drop_index(batch_op.f('ix_analytics_report_history_report_ref'))
        batch_op.drop_index(batch_op.f('ix_analytics_report_history_created_at'))

    op.drop_table('analytics_report_history')
    with op.batch_alter_table('forecast_runs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_forecast_runs_trained_at'))
        batch_op.drop_index(batch_op.f('ix_forecast_runs_target'))
        batch_op.drop_index(batch_op.f('ix_forecast_runs_status'))
        batch_op.drop_index(batch_op.f('ix_forecast_runs_run_ref'))

    op.drop_table('forecast_runs')
    with op.batch_alter_table('detected_anomalies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_detected_anomalies_severity'))
        batch_op.drop_index(batch_op.f('ix_detected_anomalies_review_status'))
        batch_op.drop_index(batch_op.f('ix_detected_anomalies_detected_at'))
        batch_op.drop_index(batch_op.f('ix_detected_anomalies_category'))
        batch_op.drop_index(batch_op.f('ix_detected_anomalies_anomaly_id'))

    op.drop_table('detected_anomalies')
    with op.batch_alter_table('business_risk_assessments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_business_risk_assessments_severity'))
        batch_op.drop_index(batch_op.f('ix_business_risk_assessments_risk_key'))
        batch_op.drop_index(batch_op.f('ix_business_risk_assessments_category'))
        batch_op.drop_index(batch_op.f('ix_business_risk_assessments_assessed_at'))

    op.drop_table('business_risk_assessments')
    with op.batch_alter_table('business_kpis', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_business_kpis_updated_at'))
        batch_op.drop_index(batch_op.f('ix_business_kpis_kpi_key'))
        batch_op.drop_index(batch_op.f('ix_business_kpis_category'))

    op.drop_table('business_kpis')
    with op.batch_alter_table('analytics_snapshots', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_analytics_snapshots_snapshot_type'))
        batch_op.drop_index(batch_op.f('ix_analytics_snapshots_snapshot_key'))
        batch_op.drop_index(batch_op.f('ix_analytics_snapshots_period_start'))
        batch_op.drop_index(batch_op.f('ix_analytics_snapshots_period_end'))
        batch_op.drop_index(batch_op.f('ix_analytics_snapshots_created_at'))

    op.drop_table('analytics_snapshots')
