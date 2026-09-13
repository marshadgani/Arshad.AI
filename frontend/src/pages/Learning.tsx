import DomainComingSoon from '../components/DomainComingSoon';
import { COMING_SOON_DOMAINS } from '../data/comingSoonDomains';

export default function Learning() {
  return <DomainComingSoon {...COMING_SOON_DOMAINS.learning} />;
}
