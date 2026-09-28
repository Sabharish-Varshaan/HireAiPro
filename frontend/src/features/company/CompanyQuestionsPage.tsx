import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Empty, Loading } from "../../components/ui";
import QuestionBankPage from "./QuestionBankPage";

export default function CompanyQuestionsPage() {
  const orgs = useQuery({ queryKey: ["orgs-mine"], queryFn: () => api.get("/organizations/mine").then((r) => r.data) });
  if (orgs.isLoading) return <Loading />;
  if (!orgs.data?.[0]) return <Empty>Create your company first.</Empty>;
  return <QuestionBankPage organizationId={orgs.data[0].id} />;
}
