import { PreferredsView } from "@/components/PreferredsView";
import { FairValues, MarketSnapshot, PreferredStory } from "@/lib/types";
import market from "../../../public/data/market_snapshot.json";
import fair from "../../../public/data/fair_values.json";
import story from "../../../public/data/preferred_story.json";

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
    />
  );
}
