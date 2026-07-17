import { CommonsView } from "@/components/CommonsView";
import { FairValues, MarketSnapshot, ShareDilution } from "@/lib/types";
import market from "../../../public/data/market_snapshot.json";
import fair from "../../../public/data/fair_values.json";
import dilution from "../../../public/data/share_dilution.json";

export const metadata = {
  title: "Commons · HEDGD",
  description:
    "Compare MSTR and ASST rNAV, balance sheets, share counts, and methodology.",
};

export default function CommonsPage() {
  return (
    <CommonsView
      initialMarket={market as MarketSnapshot}
      initialFair={fair as FairValues}
      dilution={dilution as ShareDilution}
    />
  );
}
