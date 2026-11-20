# SchoolZone News for Home Assistant

Brings Edmonton Public Schools [SchoolZone](https://schoolzone.epsb.ca) announcements into Home Assistant.

## Features

- One sensor per news stream (School, Class, Division, Trustee, SchoolZone, Transportation), including post attachments.
- Checks SchoolZone twice a day at times you choose (Home Assistant's time zone).
- A **Check now** button for an extra refresh.
- Posts are cached, so a restart doesn't trigger a refetch unless a scheduled check was missed.
- Re-authentication flow when your SchoolZone password changes.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → Custom repositories → add `https://github.com/ctf12/ha-EPSB-schoolzone-news` as an *Integration*.
2. Install **SchoolZone News** and restart Home Assistant.

### Manual

Copy `custom_components/schoolzone_news` into your Home Assistant `custom_components` folder and restart.

## Setup

Settings → Devices & services → Add integration → **SchoolZone News**. Sign in with the same username and password you use at schoolzone.epsb.ca, then pick your news streams and check times.

## License

See [LICENSE](LICENSE).
