import type { CustomField, ProjectDetail, Task, User, ViewConfig } from '../api/client';
import type { TaskPatch } from '../lib/taskUpdates';

export type { TaskPatch };

export interface ViewProps {
  tasks: Task[];
  project: ProjectDetail;
  fields: CustomField[];
  users: User[];
  config: ViewConfig;
  onOpen: (task: Task) => void;
  onUpdate: (task: Task, patch: TaskPatch) => void;
}
