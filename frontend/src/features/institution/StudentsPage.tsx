import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  Loading,
  Modal,
  PageHeader,
  Table,
  inputCls,
} from "../../components/ui";
import { useInstitution } from "./useInstitution";

const TABS = [
  ["ALL", "All Students"],
  ["PENDING", "Pending Invitations"],
  ["IMPORT", "Batch CSV Import"],
] as const;

const blank = {
  email: "",
  first_name: "",
  last_name: "",
  student_id: "",
  department: "",
  program: "",
  cohort: "",
  graduation_year: "",
};

function ImportPanel({ instId, onDone }: { instId: string; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [result, setResult] = useState<any>(null);

  const form = () => {
    const fd = new FormData();
    fd.append("file", file!);
    return fd;
  };
  const doPreview = useMutation({
    mutationFn: () =>
      api.post(`/institutions/${instId}/student-records/import/preview`, form()).then((r) => r.data),
    onSuccess: (d) => {
      setPreview(d);
      setResult(null);
    },
  });
  const doConfirm = useMutation({
    mutationFn: () =>
      api.post(`/institutions/${instId}/student-records/import/confirm`, form()).then((r) => r.data),
    onSuccess: (d) => {
      setResult(d);
      setPreview(null);
      onDone();
    },
  });
  const shown = result ?? preview;

  return (
    <Card
      title="Import Student Records via CSV"
      description="Upload a CSV roster to batch-create accounts and issue invitation links."
    >
      <div className="space-y-3">
        <p className="text-xs text-gray-500 leading-relaxed">
          Required columns: <b>email</b>, <b>first_name</b>, <b>last_name</b>, <b>student_id</b>, <b>department</b>, <b>cohort</b>, <b>graduation_year</b>.
          Departments and cohorts should match existing records. Each invited student sets their own private password.
        </p>
        <div className="flex flex-wrap gap-2 items-center">
          <input
            type="file"
            accept=".csv,text/csv"
            className="text-xs"
            data-testid="csv-file"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setPreview(null);
              setResult(null);
            }}
          />
          <Button variant="secondary" size="sm" onClick={() => doPreview.mutate()} disabled={!file || doPreview.isPending}>
            {doPreview.isPending ? "Validating CSV…" : "Preview Import"}
          </Button>
          {preview && preview.invite + preview.link_existing > 0 && (
            <Button size="sm" onClick={() => doConfirm.mutate()} disabled={doConfirm.isPending}>
              {doConfirm.isPending ? "Importing…" : `Confirm Import (${preview.invite + preview.link_existing} records)`}
            </Button>
          )}
        </div>
        <ErrorBox error={doPreview.error || doConfirm.error} />
        {shown && (
          <div className="space-y-3 pt-2" data-testid="import-summary">
            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-900">
              <strong>{result ? "Import Completed: " : "Preview Validation: "}</strong>
              {result
                ? `${result.invited} invited, ${result.linked} linked to existing accounts`
                : `${preview.invite} ready to invite, ${preview.link_existing} existing accounts to link`},{" "}
              <b className={shown.errors ? "text-red-600" : ""}>{shown.errors} errors</b> out of {shown.total} total rows.
            </div>
            <Table head={["Line", "Student Email", "Status / Action"]}>
              {shown.rows.map((r: any) => (
                <tr key={r.line} className={r.action === "ERROR" ? "bg-red-50/50" : "hover:bg-gray-50/50"}>
                  <td className="py-1.5 pr-3 text-xs font-mono">{r.line}</td>
                  <td className="pr-3 text-xs font-medium text-gray-900">{r.email}</td>
                  <td className="text-xs">
                    {r.action === "ERROR" ? (
                      <span className="text-red-700 font-semibold">{r.error}</span>
                    ) : r.action === "INVITE" ? (
                      <span className="text-emerald-700">New invitation will be sent</span>
                    ) : (
                      <span className="text-blue-700">Will link to existing registered account</span>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function StudentsPage() {
  const { inst, isLoading } = useInstitution();
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("ALL");
  const [f, setF] = useState(blank);
  const [inviteModalOpen, setInviteModalOpen] = useState(false);

  const list = useQuery({
    queryKey: ["student-records", inst?.id, tab],
    enabled: !!inst && tab !== "IMPORT",
    queryFn: () =>
      api
        .get(`/institutions/${inst.id}/student-records`, {
          params: tab === "PENDING" ? { status: "PENDING" } : {},
        })
        .then((r) => r.data),
  });
  const counts = useQuery({
    queryKey: ["student-records", inst?.id, "counts"],
    enabled: !!inst,
    queryFn: () =>
      api.get(`/institutions/${inst.id}/student-records`, { params: { status: "NONE" } }).then((r) => r.data.counts),
  });

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["student-records"] });
    qc.invalidateQueries({ queryKey: ["roster"] });
  };
  const invite = useMutation({
    mutationFn: () => api.post(`/institutions/${inst.id}/student-records/invite`, f).then((r) => r.data),
    onSuccess: () => {
      setF(blank);
      setInviteModalOpen(false);
      refresh();
    },
  });
  const act = useMutation({
    mutationFn: ({ id, what }: { id: string; what: string }) =>
      api.post(`/institutions/${inst.id}/student-records/${id}/${what}`),
    onSuccess: refresh,
  });

  if (isLoading) return <Loading />;
  if (!inst) return <Empty>No institution is linked to this account.</Empty>;

  const c = counts.data ?? {};
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF({ ...f, [k]: e.target.value });

  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title="Student Management"
        description="Invite students, manage campus enrollments, and track claimed accounts."
        actions={
          <div className="flex gap-2">
            <Button
              onClick={() => setInviteModalOpen(true)}
              size="sm"
              icon={
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
                </svg>
              }
            >
              Invite Student
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setTab("IMPORT")}
            >
              CSV Import
            </Button>
          </div>
        }
      />

      {/* Tabs and Summary Counters */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-gray-200 pb-2">
        <div className="flex gap-1.5">
          {TABS.map(([k, label]) => (
            <button
              key={k}
              onClick={() => setTab(k)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                tab === k
                  ? "bg-blue-700 text-white shadow-xs"
                  : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
              }`}
            >
              {label}
              {k === "PENDING" && c.PENDING ? ` (${c.PENDING})` : ""}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500" /> Active: <b>{c.ACTIVE ?? 0}</b>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-500" /> Pending: <b>{c.PENDING ?? 0}</b>
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-gray-400" /> Disabled: <b>{c.DISABLED ?? 0}</b>
          </span>
        </div>
      </div>

      {tab === "IMPORT" ? (
        <ImportPanel instId={inst.id} onDone={refresh} />
      ) : (
        <Card
          title={tab === "PENDING" ? "Pending Invitations" : "Enrolled Students"}
          description={
            tab === "PENDING"
              ? "Students who have been sent an invite link but have not yet registered their account."
              : "All student records registered under this institution."
          }
        >
          {list.isLoading && <Loading />}
          {list.data && list.data.students.length === 0 && (
            <Empty>
              {tab === "PENDING"
                ? "No pending invitations at this time."
                : "No students registered yet. Click Invite Student above or upload a CSV roster."}
            </Empty>
          )}
          {list.data && list.data.students.length > 0 && (
            <Table head={["Student Name", "Email", "Registration ID", "Department", "Cohort", "Class Year", "Status", "Actions"]}>
              {list.data.students.map((s: any) => (
                <tr key={s.id} className="hover:bg-gray-50/50">
                  <td className="py-2.5 pr-3 font-medium text-gray-900 text-xs">
                    {s.student_profile_id ? (
                      <Link
                        className="text-blue-700 hover:text-blue-900 underline"
                        to={`/institution/institutions/${inst.id}/students/${s.student_profile_id}`}
                      >
                        {s.name ?? s.email}
                      </Link>
                    ) : (
                      s.name ?? "—"
                    )}
                  </td>
                  <td className="pr-3 text-xs text-gray-500 font-mono">{s.email}</td>
                  <td className="pr-3 text-xs text-gray-700">{s.student_code ?? "—"}</td>
                  <td className="pr-3 text-xs text-gray-700">{s.department ?? "—"}</td>
                  <td className="pr-3 text-xs text-gray-700">{s.cohort ?? "—"}</td>
                  <td className="pr-3 text-xs text-gray-700">{s.graduation_year ?? "—"}</td>
                  <td className="pr-3">
                    <Badge tone={s.status === "ACTIVE" ? "green" : s.status === "PENDING" ? "amber" : "gray"}>
                      {s.status === "PENDING" ? "Pending invite" : s.status === "ACTIVE" ? "Active" : s.status}
                    </Badge>
                  </td>
                  <td className="space-x-1.5 whitespace-nowrap text-xs">
                    {s.status === "PENDING" && (
                      <Button variant="secondary" size="sm" onClick={() => act.mutate({ id: s.id, what: "resend" })}>
                        Resend invite
                      </Button>
                    )}
                    {s.status !== "DISABLED" ? (
                      <Button variant="danger" size="sm" onClick={() => act.mutate({ id: s.id, what: "disable" })}>
                        Disable
                      </Button>
                    ) : (
                      <Button variant="secondary" size="sm" onClick={() => act.mutate({ id: s.id, what: "enable" })}>
                        Re-enable
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          )}
          <ErrorBox error={act.error} />
        </Card>
      )}

      {/* Clean Invite Student Modal Dialog */}
      <Modal
        open={inviteModalOpen}
        onClose={() => {
          setInviteModalOpen(false);
          setF(blank);
        }}
        title="Invite Student"
      >
        <div className="space-y-4">
          <p className="text-xs text-gray-500">
            Send an official email invitation to enroll a student. They will receive a link to securely choose their own password.
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="sm:col-span-2 space-y-1">
              <label className="text-xs font-medium text-gray-700">Email Address *</label>
              <input className={inputCls} placeholder="student@institution.edu" value={f.email} onChange={set("email")} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">First Name</label>
              <input className={inputCls} placeholder="First name" value={f.first_name} onChange={set("first_name")} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Last Name</label>
              <input className={inputCls} placeholder="Last name" value={f.last_name} onChange={set("last_name")} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Student / Roll ID</label>
              <input className={inputCls} placeholder="e.g. 2023CS010" value={f.student_id} onChange={set("student_id")} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Department</label>
              <input className={inputCls} placeholder="e.g. Computer Science" value={f.department} onChange={set("department")} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Cohort</label>
              <input className={inputCls} placeholder="e.g. Batch 2026" value={f.cohort} onChange={set("cohort")} />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Graduation Year</label>
              <input className={inputCls} placeholder="e.g. 2026" value={f.graduation_year} onChange={set("graduation_year")} />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
            <Button variant="secondary" onClick={() => setInviteModalOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => invite.mutate()} disabled={!f.email || invite.isPending}>
              {invite.isPending ? "Sending…" : "Send Invitation"}
            </Button>
          </div>
          <ErrorBox error={invite.error} />
        </div>
      </Modal>
    </div>
  );
}
