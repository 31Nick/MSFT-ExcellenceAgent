export interface Task {
  resource_name: string;
  resource_id: string;
  resource_group: string;
  subscription_id: string;
  location: string;
  validation_status: string;
  custom_fields: Record<string, string>;
  notes: string;
  check_name: string;
}

export interface UserStory {
  title: string;
  recommendation_guid: string;
  impact: 'High' | 'Medium' | 'Low';
  priority: number;
  recommendation_control: string;
  potential_benefit: string;
  learn_more_link: string;
  long_description: string;
  waf_pillar: string;
  category: string;
  source: string;
  tasks: Task[];
}

export interface Feature {
  name: string;
  resource_type: string;
  resource_groups: string[];
  subscriptions: string[];
  resource_count: number;
  user_stories: UserStory[];
  total_tasks: number;
}

export interface Epic {
  name: string;
  description: string;
  total_resource_count: number;
  waf_pillars: string[];
  impact_summary: { High: number; Medium: number; Low: number };
  features: Feature[];
  total_stories: number;
  total_tasks: number;
}

export interface WorkItemHierarchy {
  epics: Epic[];
  summary: {
    epics: number;
    features: number;
    user_stories: number;
    tasks: number;
  };
}

export interface Stats {
  epics: number;
  features: number;
  user_stories: number;
  tasks: number;
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
  task_count: number;
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
  cross_reference?: CrossReferenceReport;
}

export interface ExportRequest {
  area_path: string;
  iteration_path: string;
}

export interface GitHubExportRequest {
  repo: string;
  milestone?: string;
  assignee?: string;
  extra_labels?: string;
}
