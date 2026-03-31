import type {
  Stats,
  WorkItemHierarchy,
  Pattern,
  DedupReport,
  UploadResponse,
  ExportRequest,
  CrossReferenceReport,
} from './types';

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || res.statusText);
  }
  return res.json();
}

export async function uploadFile(
  file: File,
  onProgress?: (pct: number) => void,
  advisorFile?: File | null
): Promise<UploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    });

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText));
      } else {
        reject(new ApiError(xhr.status, xhr.responseText));
      }
    });

    xhr.addEventListener('error', () => reject(new Error('Upload failed')));

    const fd = new FormData();
    fd.append('aprl_file', file);
    if (advisorFile) {
      fd.append('advisor_file', advisorFile);
    }
    xhr.send(fd);
  });
}

export async function getStats(): Promise<Stats> {
  return request<Stats>('/api/stats');
}

export async function getHierarchy(): Promise<WorkItemHierarchy> {
  return request<WorkItemHierarchy>('/api/hierarchy');
}

export async function getPatterns(): Promise<Pattern[]> {
  return request<Pattern[]>('/api/patterns');
}

export async function getDedup(): Promise<DedupReport> {
  return request<DedupReport>('/api/dedup');
}

export async function getCrossReference(): Promise<CrossReferenceReport> {
  return request<CrossReferenceReport>('/api/cross-reference');
}

export async function exportCsv(params: ExportRequest): Promise<void> {
  const res = await fetch('/api/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || res.statusText);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'ado_export.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
