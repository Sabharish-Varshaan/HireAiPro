import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  Table,
  inputCls,
  humanize,
} from "../../components/ui";

function CollapsibleAddForm({
  endpoint,
  fields,
  label,
}: {
  endpoint: string;
  fields: [string, string][];
  label: string;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [v, setV] = useState<Record<string, string>>({});

  const m = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      for (const [k] of fields) {
        if (v[k]) {
          body[k] =
            k === "claimed_skill_names"
              ? v[k].split(",").map((s) => s.trim())
              : ["start_year", "end_year"].includes(k)
              ? Number(v[k])
              : k === "gpa"
              ? Number(v[k])
              : v[k];
        }
      }
      return api.post(`/students/me/${endpoint}`, body);
    },
    onSuccess: () => {
      setV({});
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["profile-full"] });
    },
  });

  if (!open) {
    return (
      <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
        + Add {label}
      </Button>
    );
  }

  return (
    <div className="border border-gray-200 bg-gray-50/60 rounded-xl p-4 space-y-3">
      <p className="text-xs font-semibold text-gray-800">Add New {label}</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
        {fields.map(([k, ph]) => (
          <div key={k} className="space-y-1">
            <label className="text-[11px] font-medium text-gray-600">{ph}</label>
            <input
              className={inputCls}
              placeholder={ph}
              value={v[k] ?? ""}
              onChange={(e) => setV({ ...v, [k]: e.target.value })}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-2 pt-1">
        <Button
          size="sm"
          onClick={() => m.mutate()}
          disabled={m.isPending || !v[fields[0][0]]}
        >
          {m.isPending ? "Adding…" : `Save ${label}`}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      <ErrorBox error={m.error} />
    </div>
  );
}

export default function ProfilePage() {
  const qc = useQueryClient();
  const full = useQuery({
    queryKey: ["profile-full"],
    queryFn: () => api.get("/students/me/full").then((r) => r.data),
    refetchInterval: (q) => {
      const pr = (q.state.data as any)?.profile;
      return pr?.resume_document_id && ["PENDING", "PROCESSING"].includes(pr.resume_parse_status)
        ? 3000
        : false;
    },
  });
  const p = full.data?.profile;
  const claims = useQuery({
    queryKey: ["claims", p?.id, p?.resume_parse_status],
    enabled: !!p?.id,
    queryFn: () =>
      api
        .get(`/evidence/students/${p.id}/evidence`)
        .then((r) => r.data.filter((e: any) => e.source_type === "RESUME_CLAIM")),
  });
  const [basics, setBasics] = useState({ headline: "", bio: "", location: "" });
  useEffect(() => {
    if (p) setBasics({ headline: p.headline ?? "", bio: p.bio ?? "", location: p.location ?? "" });
  }, [p?.id]); // eslint-disable-line
  const saveBasics = useMutation({
    mutationFn: () => api.put("/students/me", basics),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-full"] }),
  });
  const upload = useMutation({
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
      return api.post("/students/me/resume", fd);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-full"] }),
  });

  if (full.isLoading) return <Loading />;
  if (full.error) return <ErrorBox error={full.error} onRetry={full.refetch} />;

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Student Profile & Resume"
        description="Keep your background, educational credentials, and verified experience current."
      />

      {full.data?.institution && (
        <Card title="Affiliated Institution">
          <p className="text-sm font-medium text-gray-900" data-testid="institution-card">
            {full.data.institution.name}
            {full.data.institution.cohort ? ` · ${full.data.institution.cohort}` : ""}
            {full.data.institution.graduation_year ? ` · Class of ${full.data.institution.graduation_year}` : ""}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            Your college placement cell manages campus recruitment opportunities based on your enrolled department and cohort.
          </p>
        </Card>
      )}

      {/* About Section */}
      <Card title="About You" description="Headline and summary shown to recruiting companies.">
        <div className="space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Headline</label>
              <input
                className={inputCls}
                placeholder="e.g. Computer Science Undergrad | Distributed Systems"
                value={basics.headline}
                onChange={(e) => setBasics({ ...basics, headline: e.target.value })}
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Location</label>
              <input
                className={inputCls}
                placeholder="e.g. San Francisco, CA or Bangalore, India"
                value={basics.location}
                onChange={(e) => setBasics({ ...basics, location: e.target.value })}
              />
            </div>
          </div>
          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-700">Bio</label>
            <textarea
              className={inputCls}
              rows={3}
              placeholder="Brief professional summary…"
              value={basics.bio}
              onChange={(e) => setBasics({ ...basics, bio: e.target.value })}
            />
          </div>
          <div className="flex items-center gap-3">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => saveBasics.mutate()}
              disabled={saveBasics.isPending}
            >
              {saveBasics.isPending ? "Saving…" : "Save Changes"}
            </Button>
            {saveBasics.isSuccess && (
              <span className="text-xs font-medium text-emerald-700">✓ Saved successfully</span>
            )}
          </div>
          <ErrorBox error={saveBasics.error} />
        </div>
      </Card>

      {/* Resume Upload & Claimed Skills */}
      <Card
        title="Resume & Extracted Skills"
        actions={
          <Badge>
            {p?.resume_document_id ? humanize(p.resume_parse_status) : "Not uploaded"}
          </Badge>
        }
      >
        <div className="space-y-3">
          <div className="flex flex-col sm:flex-row sm:items-center gap-3 p-3 bg-gray-50 rounded-xl border border-gray-200 text-xs">
            <input
              type="file"
              accept=".pdf,.docx,.txt"
              onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])}
              className="text-xs text-gray-700"
            />
            {upload.isPending && <span className="text-xs text-amber-700">Uploading and parsing document…</span>}
          </div>
          <ErrorBox error={upload.error} />
          {p?.resume_parse_status === "FAILED" && (
            <p className="text-xs text-red-600">Resume parsing encountered an error — please upload again to retry.</p>
          )}
          <p className="text-xs text-gray-500">
            Skills extracted from your resume are recorded as <b>unverified claims</b>. They help match relevant job blueprints but require assessment verification to earn verified badges.
          </p>
          {(claims.data ?? []).length > 0 && (
            <div className="space-y-1.5 pt-2 border-t border-gray-100">
              <p className="text-xs font-semibold text-gray-700">Extracted Resume Claims:</p>
              <div className="flex flex-wrap gap-1.5">
                {claims.data.map((c: any) => (
                  <Badge key={c.id} tone="gray">
                    {c.skill_name}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* Education */}
      <Card title="Education Credentials">
        <div className="space-y-3">
          {full.data.education.length === 0 ? (
            <Empty>No education credentials added yet.</Empty>
          ) : (
            <Table head={["Institution", "Degree", "Field of Study", "Duration"]}>
              {full.data.education.map((e: any) => (
                <tr key={e.id} className="hover:bg-gray-50/50">
                  <td className="py-2 pr-3 font-medium text-gray-900">{e.institution_name}</td>
                  <td className="pr-3 text-xs">{e.degree}</td>
                  <td className="pr-3 text-xs">{e.field_of_study}</td>
                  <td className="text-xs font-mono text-gray-600">
                    {e.start_year}–{e.end_year}
                  </td>
                </tr>
              ))}
            </Table>
          )}
          <CollapsibleAddForm
            endpoint="education"
            label="Education"
            fields={[
              ["institution_name", "Institution Name"],
              ["degree", "Degree (e.g. B.Tech)"],
              ["field_of_study", "Field of Study"],
              ["start_year", "Start Year"],
              ["end_year", "End Year"],
            ]}
          />
        </div>
      </Card>

      {/* Experience */}
      <Card title="Work Experience">
        <div className="space-y-3">
          {full.data.experience.length === 0 ? (
            <Empty>No work experience added yet.</Empty>
          ) : (
            <div className="divide-y divide-gray-100">
              {full.data.experience.map((e: any) => (
                <div key={e.id} className="py-2.5 text-xs space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-900">{e.title}</span>
                    <span className="text-gray-400">·</span>
                    <span className="font-medium text-gray-700">{e.company_name}</span>
                  </div>
                  <p className="text-gray-600 leading-relaxed">{e.description}</p>
                </div>
              ))}
            </div>
          )}
          <CollapsibleAddForm
            endpoint="experience"
            label="Experience"
            fields={[
              ["company_name", "Company"],
              ["title", "Job Title"],
              ["description", "Description of responsibilities"],
            ]}
          />
        </div>
      </Card>

      {/* Projects */}
      <Card title="Projects & Technical Work">
        <div className="space-y-3">
          {full.data.projects.length === 0 ? (
            <Empty>No projects added yet.</Empty>
          ) : (
            <div className="divide-y divide-gray-100">
              {full.data.projects.map((e: any) => (
                <div key={e.id} className="py-2.5 text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold text-gray-900">{e.title}</span>
                    {e.url && (
                      <a
                        href={e.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        Project Link ↗
                      </a>
                    )}
                  </div>
                  <p className="text-gray-600 leading-relaxed">{e.description}</p>
                  {(e.claimed_skill_names ?? []).length > 0 && (
                    <div className="flex flex-wrap gap-1 pt-0.5">
                      {e.claimed_skill_names.map((sn: string) => (
                        <span key={sn} className="text-[11px] px-2 py-0.5 rounded bg-gray-100 text-gray-600">
                          {sn}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          <CollapsibleAddForm
            endpoint="projects"
            label="Project"
            fields={[
              ["title", "Project Title"],
              ["description", "Project Description"],
              ["url", "Repository or Demo URL"],
              ["claimed_skill_names", "Skills used (comma-separated)"],
            ]}
          />
        </div>
      </Card>

      {/* Certifications */}
      <Card title="Licenses & Certifications">
        <div className="space-y-3">
          {full.data.certifications.length === 0 ? (
            <Empty>No certifications added yet.</Empty>
          ) : (
            <div className="divide-y divide-gray-100">
              {full.data.certifications.map((e: any) => (
                <div key={e.id} className="py-2.5 text-xs flex items-center justify-between">
                  <div>
                    <p className="font-semibold text-gray-900">{e.name}</p>
                    <p className="text-gray-500">{e.issuer}</p>
                  </div>
                  {e.credential_url && (
                    <a
                      href={e.credential_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-blue-600 hover:underline text-xs"
                    >
                      Verify Credential ↗
                    </a>
                  )}
                </div>
              ))}
            </div>
          )}
          <CollapsibleAddForm
            endpoint="certifications"
            label="Certification"
            fields={[
              ["name", "Certification Name"],
              ["issuer", "Issuing Organization"],
              ["credential_url", "Verification URL (optional)"],
            ]}
          />
        </div>
      </Card>
    </div>
  );
}
