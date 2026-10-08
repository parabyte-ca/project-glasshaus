import type { CustomField, ProjectDetail, Task, User, ViewConfig } from '../api/client';

export type TaskPatch = Record<string, unknown>;

export interface ViewProps {
  tasks: Task[];
  project: ProjectDetail;
  fields: CustomField[];
  users: User[];
  config: ViewConfig;
  onOpen: (task: Task) => void;
  onUpdate: (task: Task, patch: TaskPatch) => void;
}
