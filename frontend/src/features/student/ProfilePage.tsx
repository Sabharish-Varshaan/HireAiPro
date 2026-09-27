import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../../api/client";

export default function ProfilePage() {
  const qc = useQueryClient();
  const { data: profile } = useQuery({
    queryKey: ["student-me"],
    queryFn: () => api.get("/students/me").then((r) => r.data),
  });

  const uploadResume = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post("/students/me/resume", fd, { headers: { "Content-Type": "multipart/form-data" } });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["student-me"] }),
  });

  return (
    <div className="max-w-xl space-y-4">
      <h1 className="text-lg font-semibold text-gray-900">Resume</h1>
      <p className="text-sm text-gray-600">Status: {profile?.resume_parse_status ?? "—"}</p>
      <input
        type="file"
        accept=".pdf,.docx"
        onChange={(e) => e.target.files?.[0] && uploadResume.mutate(e.target.files[0])}
        className="text-sm"
      />
      <p className="text-xs text-gray-400">
        Resume-derived skills are stored as unverified claims and do not count toward your
        verified skill scores until confirmed through assessments or interviews.
      </p>
    </div>
  );
}
