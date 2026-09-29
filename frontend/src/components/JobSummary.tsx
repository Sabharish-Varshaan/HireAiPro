import { Badge } from "./ui";

/** One place that renders a job's posting facts from the server's `display` strings; nulls are simply not shown. */
export function JobFacts({ job, compact }: { job: any; compact?: boolean }) {
  const d = job.display ?? {};
  const closed = d.application_deadline && d.applications_open === false;
  return (
    <div className="space-y-0.5 text-xs text-gray-600" data-testid="job-facts">
      {d.headline && <p data-testid="job-headline" className="text-gray-700">{d.headline}</p>}
      {d.compensation && <p data-testid="job-comp">{d.compensation}{d.internship_duration ? ` · ${d.internship_duration}` : ""}</p>}
      {!d.compensation && d.internship_duration && <p>{d.internship_duration}</p>}
      {d.full_time_package && <p data-testid="job-ft">Full-time package: {d.full_time_package}</p>}
      {!compact && d.conversion && <p>{d.conversion}</p>}
      {!compact && d.experience && <p>Experience: {d.experience}</p>}
      {!compact && job.number_of_openings != null && <p>{job.number_of_openings} opening{job.number_of_openings === 1 ? "" : "s"}</p>}
      {d.application_deadline && (
        <p data-testid="job-deadline" className={closed ? "text-red-600" : ""}>
          {closed ? "Applications closed " : "Applications close "}{new Date(d.application_deadline).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
        </p>)}
      {closed && <Badge tone="red">Closed</Badge>}
    </div>
  );
}
