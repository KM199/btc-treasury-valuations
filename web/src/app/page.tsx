import { LiveHome } from "@/components/LiveHome";
import { FairValues, MarketSnapshot } from "@/lib/types";
import market from "../../public/data/market_snapshot.json";
import fair from "../../public/data/fair_values.json";

export default function HomePage() {
  return (
    <LiveHome
      initialMarket={market as MarketSnapshot}
      initialFair={fair as FairValues}
    />
  );
}
