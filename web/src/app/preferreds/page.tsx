import { PreferredsView } from "@/components/PreferredsView";
import {
  FairValues,
  MarketSnapshot,
  PreferredStory,
  YieldCurveChart,
} from "@/lib/types";
import market from "../../../public/data/market_snapshot.json";
import fair from "../../../public/data/fair_values.json";
import story from "../../../public/data/preferred_story.json";
import yieldCurve from "../../../public/data/yield_curve.json";

export const metadata = {
  title: "Preferreds · HEDGD",
  description:
    "Bitcoin-backed preferred equities: get-even months, path NPV, sensitivities, and wipeout hedges.",
};

export default function PreferredsPage() {
  return (
    <PreferredsView
      initialMarket={market as MarketSnapshot}
      initialFair={fair as FairValues}
      story={story as PreferredStory}
      yieldCurve={yieldCurve as YieldCurveChart}
    />
  );
}
