import { useCallback, useState, type DragEvent } from 'react';
import { Upload, FileUp } from 'lucide-react';
import Spinner from './Spinner';

interface Props {
  onFile: (file: File) => void;
  uploading: boolean;
  progress: number;
}

export default function FileDropZone({ onFile, uploading, progress }: Props) {
  const [dragging, setDragging] = useState(false);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) onFile(file);
    },
    [onFile]
  );

  const handleChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) onFile(file);
    },
    [onFile]
  );

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={`relative border-2 border-dashed rounded-xl p-12 text-center transition-colors
        ${dragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-blue-400 hover:bg-gray-50'}
        ${uploading ? 'pointer-events-none opacity-70' : 'cursor-pointer'}`}
      onClick={() => {
        if (!uploading) document.getElementById('file-input')?.click();
      }}
    >
      <input
        id="file-input"
        type="file"
        accept=".json,.csv,.xlsx"
        onChange={handleChange}
        className="hidden"
      />

      {uploading ? (
        <div className="flex flex-col items-center gap-3">
          <Spinner className="w-10 h-10" />
          <p className="text-gray-600 font-medium">Processing… {progress}%</p>
          <div className="w-64 h-2 bg-gray-200 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <div className="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center">
            {dragging ? (
              <FileUp className="w-8 h-8 text-blue-500" />
            ) : (
              <Upload className="w-8 h-8 text-blue-500" />
            )}
          </div>
          <div>
            <p className="text-lg font-semibold text-gray-800">
              {dragging ? 'Drop your file here' : 'Upload APRL Assessment File'}
            </p>
            <p className="text-sm text-gray-500 mt-1">
              Drag & drop or click to select a JSON, CSV, or XLSX file
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
