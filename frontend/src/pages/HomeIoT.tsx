import DomainComingSoon from '../components/DomainComingSoon';
import { COMING_SOON_DOMAINS } from '../data/comingSoonDomains';

export default function HomeIoT() {
  return <DomainComingSoon {...COMING_SOON_DOMAINS['home-iot']} />;
}
