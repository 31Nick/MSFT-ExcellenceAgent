export interface AffectedResource {
  resource_name: string;
  resource_id: string;
  resource_group: string;
  subscription_id: string;
  location: string;
  validation_status: string;
  notes: string;
  check_name: string;
  custom_fields: Record<string, string>;
}

export interface Recommendation {
  title: string;
  recommendation_guid: string;
  impact: 'High' | 'Medium' | 'Low';
  recommendation_control: string;
  potential_benefit: string;
  learn_more_link: string;
  long_description: string;
  waf_pillar: string;
  category: string;
  source: string;
  advisor_metadata: Record<string, string>;
  affected_resources: AffectedResource[];
}

export interface UserStory {
  title: string;
  impact: 'High' | 'Medium' | 'Low';
  priority: number;
  category: string;
  source: string;
  waf_pillars: string[];
  resource_count: number;
  recommendations: Recommendation[];
}

export interface Feature {
  name: string;
  resource_type: string;
  resource_groups: string[];
  subscriptions: string[];
  resource_count: number;
  user_stories: UserStory[];
  total_recommendations: number;
}

export interface Epic {
  name: string;
  description: string;
  total_resource_count: number;
  waf_pillars: string[];
  impact_summary: { High: number; Medium: number; Low: number };
  features: Feature[];
  total_stories: number;
  total_recommendations: number;
}

export interface WorkItemHierarchy {
  epics: Epic[];
  summary: {
    epics: number;
    features: number;
    user_stories: number;
    recommendations: number;
  };
}

export interface Stats {
  epics: number;
  features: number;
  user_stories: number;
  recommendations: number;
  impact_counts: { High: number; Medium: number; Low: number };
  has_data: boolean;
}

export interface DedupReport {
  original_count: number;
  deduplicated_count: number;
  rows_saved: number;
  duplicate_groups: {
    key: string;
    count: number;
    resources: string[];
  }[];
}

export interface Pattern {
  name: string;
  description: string;
  affected_epics: string[];
  story_count: number;
  recommendation_count: number;
  is_cross_epic: boolean;
  recommendations: string[];
}

export interface CrossReferenceReport {
  has_data: boolean;
  total_aprl_rows: number;
  total_advisor_rows: number;
  total_merged_rows: number;
  matched_resources_count: number;
  aprl_only_resources_count: number;
  advisor_only_resources_count: number;
  duplicate_recommendations_count: number;
  matched_resources: string[];
  aprl_only_resources: string[];
  advisor_only_resources: string[];
  duplicate_recommendations: {
    resource: string;
    aprl_title: string;
    advisor_title: string;
    similarity: number;
  }[];
}

export interface UploadResponse {
  success: boolean;
  stats: Stats;
  message: string;
  app_name?: string;
  new_items_processed?: number;
  items_skipped_duplicate?: number;
  apps_processed?: string[];
  cross_reference?: CrossReferenceReport;
}

export interface ExportRequest {
  area_path: string;
  iteration_path: string;
}

// ── Sync types ──────────────────────────────────────────────────────────

export interface CustomerInfo {
  slug: string;
  customer_name: string;
}

export interface CustomerDetail extends CustomerInfo {
  organization: string;
  project: string;
  team: string;
  area_path: string;
  iteration_path: string;
  pat_configured: boolean;
  type_mapping: {
    epic: string;
    feature: string;
    story: string;
    task: string;
  };
}

export interface PlannedItemInfo {
  stable_key: string;
  work_item_type: string;
  title: string;
  action: string;
  parent_stable_key: string;
}

export interface SyncPlanResponse {
  customer: string;
  summary: {
    create: number;
    update: number;
    relink: number;
    unchanged: number;
    orphaned: number;
    total: number;
  };
  to_create: PlannedItemInfo[];
  to_update: PlannedItemInfo[];
  to_relink: PlannedItemInfo[];
  unchanged: PlannedItemInfo[];
  orphaned: PlannedItemInfo[];
}

export interface SyncPushResponse {
  success: boolean;
  run_id: number;
  status: string;
  items_created: number;
  items_updated: number;
  items_linked: number;
  items_unchanged: number;
  items_failed: number;
  items_orphaned: number;
  errors: string[];
}

export interface SyncRunInfo {
  id: number;
  status: string;
  started_at: string;
  completed_at: string | null;
  items_created: number;
  items_updated: number;
  items_linked: number;
  items_unchanged: number;
  items_failed: number;
  items_orphaned: number;
}

export interface SyncStatusResponse {
  customer: string;
  total_items: number;
  status_counts: Record<string, number>;
  latest_run: SyncRunInfo | null;
}
