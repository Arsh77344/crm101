-- A first calendar, seeded so the campaign agent has something to see tonight.
--
-- Read this as a planning aid, not as a panchang. Every lunar date below is
-- marked Approximate because the sources genuinely disagree, and the owner's
-- rule -- promotion starts about three weeks out -- is what the campaigns are
-- built against. Where no source stated a 2027 date, the row is seeded with no
-- date at all rather than with a date worked out here: an empty field is honest
-- and a guessed one is not.
--
-- The whole block runs only while the table is empty, so re-running it adds
-- nothing.

insert into occasions
  (name, occasion_date, until_date, date_basis, lead_weeks, kind, region,
   meaning, what_sells, avoid, note)
select * from (values
  ('Wedding season, winter', date '2026-11-23', date '2026-12-15', 'Approximate', 2,
   'Wedding season', 'North India',
   'The winter run of wedding dates. Buying is done by families rather than by one person, and often months ahead of the day itself.',
   'Trousseau sets, gifting pieces for the bride''s side, heavy silk for the mother of the bride.',
   'Do not pitch this as a sale. A family buying for a wedding is not looking for a discount, and a discount reads as a lower-grade piece.',
   'Running now. The window is approximate; exact muhurat dates come from a panchang.'),

  ('Margazhi', date '2026-12-16', date '2027-01-14', 'Fixed', 3,
   'Retail moment', 'Tamil Nadu, Chennai',
   'The Tamil month given to music and devotion, and the season of the Chennai concert circuit. Dressing for a kutcheri is its own tradition.',
   'Quiet, fine, traditional pieces. Cotton and light silk in the daytime, deeper silk for evening concerts.',
   'Nothing loud or costume-like. This audience reads over-ornament as new money.',
   'Solar, so the window holds year to year.'),

  ('Lohri', date '2027-01-14', null, 'Fixed', 3, 'Festival', 'Punjab, North India',
   'The end of the long nights, marked round a bonfire at the close of winter.',
   'Warm, bright, celebratory colour. A shawl worn with it.',
   null, null),

  ('Makar Sankranti', date '2027-01-15', null, 'Fixed', 3, 'Festival', 'Pan-India',
   'The sun turning north. One of the few Indian festivals fixed to the solar calendar, so it holds the same date most years.',
   'Yellow and the colours of the harvest. Gifting between households.',
   null, 'Solar, so this date is dependable.'),

  ('Thai Pongal', date '2027-01-15', date '2027-01-18', 'Fixed', 3, 'Festival', 'Tamil Nadu',
   'A four-day harvest thanksgiving, the first day of the Tamil month of Thai. A new garment is part of the day.',
   'New pieces worn on the first morning. Traditional weave, nothing experimental.',
   null, 'Solar. Published for 2027 as Friday 15 January.'),

  ('Maha Shivratri', date '2027-03-06', null, 'Approximate', 3, 'Festival', 'Pan-India, strongest in Varanasi',
   'The night given to Shiva. In Varanasi it is the city''s own night more than anywhere else.',
   'Deep, sober colour. Pieces with a devotional rather than festive register.',
   null, 'Sources agree on 6 March 2027.'),

  ('Holi', date '2027-03-22', null, 'Approximate', 3, 'Festival', 'North India',
   'The spring festival of colour, preceded the evening before by Holika Dahan.',
   'Nothing precious is worn into the colour itself. The buying is for the evening after, and for the gifting that goes with it.',
   'Do not photograph a fine silk piece covered in colour. Anyone who owns silk knows what powder does to it.',
   'Published as both 22 and 23 March 2027; 22 is the majority reading. Confirm before printing a date.'),

  ('Gudi Padwa and Ugadi', date '2027-04-07', null, 'Approximate', 3, 'Festival', 'Maharashtra, Karnataka, Andhra Pradesh, Telangana',
   'The new year in the Deccan, and one of the handful of days considered auspicious enough to begin anything on.',
   'New pieces bought to start the year in. Traditional regional weave.',
   null, 'Also the first day of Chaitra Navratri.'),

  ('Puthandu', date '2027-04-14', null, 'Fixed', 3, 'Festival', 'Tamil Nadu',
   'Tamil New Year, the first day of Chithirai.',
   'A new garment for the morning. Regional weave strongly preferred.',
   null, 'Solar: Chithirai 1 is 14 April almost every year, occasionally the 13th or 15th.'),

  ('Ram Navami', date '2027-04-15', null, 'Approximate', 3, 'Festival', 'Pan-India',
   'The birth of Rama, closing Chaitra Navratri.', null, null, null),

  ('Akshaya Tritiya', date '2027-05-09', null, 'Approximate', 4, 'Festival', 'Pan-India',
   'The day on which every hour is auspicious, so nothing needs timing against a chart. Traditionally the day to buy something lasting -- gold above all, and by extension anything meant to be kept and handed on.',
   'The single best day in the year for a piece bought as an heirloom rather than for an outfit. Lead with permanence, not with occasion.',
   'Do not discount. The whole meaning of the day is that what you buy holds its value.',
   'Published as both 8 and 9 May 2027; 9 is the majority reading. Four weeks of lead rather than three, because the intent forms early.'),

  ('Aadi', date '2027-07-16', date '2027-08-16', 'Fixed', 2, 'Retail moment', 'Tamil Nadu',
   'The Tamil month of the monsoon peak and of goddess worship. Weddings are not held in it, and by long custom the shops discount heavily through it -- the Aadi sale is an institution in Tamil Nadu.',
   'Volume rather than bridal. Pieces bought for the self and for temple visits, and the Aadi Fridays.',
   'Do not run a bridal or trousseau campaign into Aadi. Weddings are deliberately avoided in this month and the pitch will read as ignorant.',
   'Solar window, roughly mid-July to mid-August.'),

  ('Raksha Bandhan', date '2027-08-17', null, 'Approximate', 3, 'Festival', 'North India, Maharashtra',
   'The thread tied by a sister, and the obligation it places on a brother.',
   'Gifting, and almost always bought by a man for a woman. Write for the buyer, not the wearer.',
   null, 'Every source consulted gives 17 August 2027.'),

  ('Krishna Janmashtami', date '2027-08-25', null, 'Approximate', 3, 'Festival', 'Pan-India, strongest in Mathura and Vrindavan',
   'The midnight birth of Krishna.', null, null, null),

  ('Hartalika Teej', date '2027-09-03', null, 'Approximate', 3, 'Festival', 'North India, Rajasthan',
   'Kept by married women, and by unmarried women for a good match. Green is the colour of the day.',
   'Green, and the full traditional register. One of the clearest single-colour occasions in the year.',
   null, null),

  ('Ganesh Chaturthi', date '2027-09-04', null, 'Approximate', 3, 'Festival', 'Maharashtra, Karnataka',
   'Ten days of Ganesh in the house and on the street, ending in the immersion.',
   'Nauvari and the Maharashtrian register. Bright, worn in company, photographed constantly.',
   null, null),

  ('Sharad Navratri', date '2027-09-30', date '2027-10-09', 'Approximate', 4, 'Festival', 'Gujarat, Bengal, Pan-India',
   'Nine nights of the goddess, ending in Dussehra. In Gujarat it is nine nights of garba, and many households keep a colour for each night.',
   'The longest selling window of the year: nine distinct outfits, planned in advance. The colour-per-night custom is worth building a whole run around.',
   null, 'Four weeks of lead: people plan nine nights, not one. Published as beginning 30 September 2027.'),

  ('Durga Puja', date '2027-10-06', date '2027-10-09', 'Approximate', 4, 'Festival', 'Bengal, Assam, Odisha',
   'The four days from Saptami to Dashami. The red-bordered white sari is the most recognisable garment in the Indian year.',
   'One outfit per day, and the red-and-white register on Dashami. A Bengali buyer knows exactly what the weave should be.',
   'Do not treat it as a generic festival. Getting the Bengali specifics wrong is worse here than anywhere else on this calendar.',
   'Saptami published as 6 October 2027.'),

  ('Dussehra', date '2027-10-09', null, 'Approximate', 3, 'Festival', 'Pan-India',
   'The tenth day. Another of the days on which anything may be begun without consulting a chart.',
   'Auspicious buying, much like Akshaya Tritiya but less exclusively about gold.',
   null, null),

  ('Karva Chauth', null, null, 'Approximate', 3, 'Festival', 'North India, Punjab',
   'A day-long fast kept by a wife, broken on sight of the moon. Dressed as formally as a wedding day, often in the wedding colours.',
   'Red and deep pink, heavy work, the bridal register worn by a married woman rather than a bride. Frequently bought by the husband.',
   null, 'No 2027 date confirmed. It falls roughly nine days before Diwali -- fill this in from a panchang you trust.'),

  ('Dhanteras', null, null, 'Approximate', 3, 'Festival', 'Pan-India',
   'The day of the Diwali run on which buying itself is the ritual. Metal traditionally, but it has widened to anything of value.',
   'The highest-intent buying day of the Diwali window.',
   null, 'No 2027 date confirmed here. It falls two days before Diwali -- fill it in alongside the Diwali date.'),

  ('Diwali', date '2027-10-29', null, 'Approximate', 4, 'Festival', 'Pan-India',
   'The festival of lights, and the largest gifting and buying season in the Indian year. Lakshmi Puja is its central night.',
   'Everything. New pieces for the household, gifting across families, and the year''s heaviest silk.',
   null, 'Published as both 27 and 29 October 2027; 29 is the majority reading. Four weeks of lead, and in practice the run-up starts with Navratri.'),

  ('Dev Deepawali', date '2027-11-13', null, 'Approximate', 3, 'Festival', 'Varanasi',
   'Fifteen days after Diwali, when every step of every ghat in Varanasi is lit with earthen lamps. The city''s own festival, and the brand''s own city.',
   'The one occasion on this calendar where the place in the photograph is the story. Shoot it on the ghats or not at all.',
   null, 'The strongest local hook available to a Varanasi house. Published as 13 November 2027.'),

  ('Karthigai Deepam', null, null, 'Approximate', 3, 'Festival', 'Tamil Nadu',
   'The Tamil festival of lamps, kept in the month of Karthigai.',
   'Traditional silk, worn to the temple.',
   null, 'No 2027 date confirmed here. It falls in the Tamil month beginning mid-November.')
) as v(name, occasion_date, until_date, date_basis, lead_weeks, kind, region,
       meaning, what_sells, avoid, note)
where not exists (select 1 from occasions);
