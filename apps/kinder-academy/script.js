// 요일 순서를 한 곳에서 관리합니다. 현재 요구사항은 월요일부터 토요일까지입니다.
const days = ["월", "화", "수", "목", "금", "토"];

// localStorage에 저장할 때 사용할 이름입니다.
const storageKey = "hawonSchedules";

// Firebase 콘솔에서 받은 설정값을 여기에 붙여 넣으면 가족이 같은 데이터를 공유할 수 있습니다.
// 예:
// const firebaseConfig = {
//   apiKey: "...",
//   authDomain: "...",
//   projectId: "...",
//   storageBucket: "...",
//   messagingSenderId: "...",
//   appId: "...",
// }; 
// Your web app's Firebase configuration
// For Firebase JS SDK v7.20.0 and later, measurementId is optional
const firebaseConfig = {
  apiKey: "AIzaSyCKGv2U1-pvwWMflGECiHcvw6pJlXBf80E",
  authDomain: "kidsplanner-4c634.firebaseapp.com",
  projectId: "kidsplanner-4c634",
  storageBucket: "kidsplanner-4c634.firebasestorage.app",
  messagingSenderId: "886965876998",
  appId: "1:886965876998:web:7a26768401c4c76eb74687",
  measurementId: "G-CHEXNL8NSK"
};

const firestoreCollectionName = "schedules";
const firebaseAppCdnUrl = "https://www.gstatic.com/firebasejs/10.12.5/firebase-app.js";
const firebaseFirestoreCdnUrl = "https://www.gstatic.com/firebasejs/10.12.5/firebase-firestore.js";

let firestoreDb = null;
let firestoreSchedulesCollection = null;
let firestoreApi = null;
let isFirestoreReady = false;
let firestoreStorageReadyPromise = null;

const board = document.querySelector("#scheduleBoard");
const dialog = document.querySelector("#scheduleDialog");
const form = document.querySelector("#scheduleForm");
const currentDate = document.querySelector("#currentDate");
const currentTime = document.querySelector("#currentTime");
const boardDateInput = document.querySelector("#boardDateInput");
const pickupCountdown = document.querySelector("#pickupCountdown");
const pickupAlert = document.querySelector("#pickupAlert");
const openAddFormButton = document.querySelector("#openAddForm");
const sharePageButton = document.querySelector("#sharePageButton");
const closeFormButton = document.querySelector("#closeForm");
const cancelFormButton = document.querySelector("#cancelForm");
const editIdInput = document.querySelector("#editIdInput");
const dayInput = document.querySelector("#dayInput");
const dateInput = document.querySelector("#dateInput");
const startTimeInput = document.querySelector("#startTimeInput");
const endTimeInput = document.querySelector("#endTimeInput");
const academyTypeInput = document.querySelector("#academyTypeInput");
const academyInput = document.querySelector("#academyInput");
const managerPhoneInput = document.querySelector("#managerPhoneInput");
const academyPhoneInput = document.querySelector("#academyPhoneInput");
const academyUrlInput = document.querySelector("#academyUrlInput");
const dropoffPlaceInput = document.querySelector("#dropoffPlaceInput");
const memoInput = document.querySelector("#memoInput");
const submitButton = document.querySelector("#submitButton");

let selectedBoardDateText = getTodayText();

// 저장된 일정이 있으면 불러오고, 없으면 빈 배열로 시작합니다.
let schedules = getUniqueSchedules(loadSchedulesFromLocalStorage());

// Firebase 설정값이 비어 있으면 Firestore 대신 LocalStorage만 사용합니다.
function hasFirebaseConfig() {
  return Boolean(firebaseConfig.apiKey && firebaseConfig.projectId && firebaseConfig.appId);
}

// LocalStorage에서 일정을 불러옵니다. Firestore 실패 시 fallback으로 사용합니다.
function loadSchedulesFromLocalStorage() {
  try {
    const savedSchedules = JSON.parse(localStorage.getItem(storageKey));
    return Array.isArray(savedSchedules) ? savedSchedules : [];
  } catch (error) {
    console.warn("LocalStorage 스케줄을 읽지 못했습니다.", error);
    return [];
  }
}

// LocalStorage에 일정을 저장합니다. Firestore 연결 실패 시 백업 저장소 역할도 합니다.
function saveSchedulesToLocalStorage(nextSchedules = schedules) {
  const uniqueSchedules = getUniqueSchedules(nextSchedules);
  localStorage.setItem(storageKey, JSON.stringify(uniqueSchedules));

  if (nextSchedules === schedules) {
    schedules = uniqueSchedules;
  }

  return uniqueSchedules;
}

// 복사 등록이나 연속 클릭으로 같은 일정이 두 번 보이지 않도록 비교용 값을 만듭니다.
function getScheduleDuplicateKey(schedule) {
  const normalizedSchedule = normalizeSchedule(schedule);

  return [
    normalizedSchedule.day,
    normalizedSchedule.date,
    normalizedSchedule.startTime,
    normalizedSchedule.endTime,
    normalizedSchedule.academyType,
    normalizedSchedule.academy,
  ]
    .map((value) => String(value || "").trim().toLowerCase())
    .join("|");
}

// 화면에 보여 줄 때 같은 일정은 한 번만 남깁니다.
function getUniqueSchedules(scheduleList) {
  const checkedKeys = new Set();

  return scheduleList.filter((schedule) => {
    const duplicateKey = getScheduleDuplicateKey(schedule);

    if (checkedKeys.has(duplicateKey)) {
      return false;
    }

    checkedKeys.add(duplicateKey);
    return true;
  });
}

// 같은 요일, 같은 시간, 같은 학원 일정이 이미 있는지 찾습니다.
function findDuplicateSchedule(scheduleData) {
  const duplicateKey = getScheduleDuplicateKey(scheduleData);

  return getUniqueSchedules(schedules).find((schedule) => getScheduleDuplicateKey(schedule) === duplicateKey);
}

// 같은 일정은 같은 Firestore 문서 ID를 사용해 중복 문서가 생기지 않게 합니다.
function getScheduleDocumentId(scheduleData) {
  return encodeURIComponent(getScheduleDuplicateKey(scheduleData));
}

// Firestore 문서를 화면에서 사용하는 일정 객체로 바꿉니다.
function getScheduleFromFirestoreDoc(documentSnapshot) {
  return {
    id: documentSnapshot.id,
    ...documentSnapshot.data(),
  };
}

// Firestore에 저장할 때 id는 문서 ID로 쓰고, 필드에서는 제외합니다.
function getScheduleDataForFirestore(schedule) {
  const { id, ...scheduleData } = schedule;
  return scheduleData;
}

// Firestore를 초기화하고 가족이 공유하는 schedules 컬렉션을 실시간으로 구독합니다.
async function initializeFirestoreStorage() {
  if (!hasFirebaseConfig()) {
    console.info("Firebase 설정값이 없어 LocalStorage를 사용합니다.");
    return;
  }

  try {
    const [{ initializeApp }, firestoreModule] = await Promise.all([
      import(firebaseAppCdnUrl),
      import(firebaseFirestoreCdnUrl),
    ]);
    firestoreApi = firestoreModule;

    const app = initializeApp(firebaseConfig);
    firestoreDb = firestoreApi.getFirestore(app);
    firestoreSchedulesCollection = firestoreApi.collection(firestoreDb, firestoreCollectionName);

    // 첫 연결이 실제로 가능한지 확인합니다. 실패하면 catch에서 LocalStorage fallback을 유지합니다.
    const firstSnapshot = await firestoreApi.getDocs(firestoreSchedulesCollection);

    // 처음 Firebase를 붙였을 때 Firestore가 비어 있으면 기존 LocalStorage 일정을 한 번 옮깁니다.
    if (firstSnapshot.empty && schedules.length > 0) {
      await uploadLocalSchedulesToFirestore();
    }

    isFirestoreReady = true;

    firestoreApi.onSnapshot(
      firestoreSchedulesCollection,
      (snapshot) => {
        schedules = getUniqueSchedules(snapshot.docs.map(getScheduleFromFirestoreDoc));
        saveSchedulesToLocalStorage(schedules);
        renderBoard();
        updateHeaderStatus();
      },
      (error) => {
        console.warn("Firestore 실시간 동기화가 끊겨 LocalStorage를 사용합니다.", error);
        isFirestoreReady = false;
      }
    );
  } catch (error) {
    console.warn("Firestore 연결에 실패해 LocalStorage를 사용합니다.", error);
    isFirestoreReady = false;
  }
}

// 기존 LocalStorage 일정을 Firestore로 옮깁니다. 문서 ID는 기존 id를 유지해 중복을 줄입니다.
async function uploadLocalSchedulesToFirestore() {
  const uploadJobs = schedules.map((schedule, index) => {
    const documentId = schedule.id ? String(schedule.id) : `${getScheduleDocumentId(schedule)}-${index}`;
    const documentRef = firestoreApi.doc(firestoreDb, firestoreCollectionName, documentId);

    return firestoreApi.setDoc(documentRef, getScheduleDataForFirestore({ ...schedule, id: documentId }));
  });

  await Promise.all(uploadJobs);
}

// 날짜를 보기 좋은 한국어 형식으로 바꿉니다.
function formatDate(dateText) {
  if (!dateText) return "날짜 미정";

  const date = new Date(`${dateText}T00:00:00`);
  return new Intl.DateTimeFormat("ko-KR", {
    month: "long",
    day: "numeric",
  }).format(date);
}

// 날짜를 YYYY-MM-DD 형식으로 만듭니다.
function getDateText(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

// 오늘 날짜를 기본값으로 넣기 위해 YYYY-MM-DD 형식으로 만듭니다.
function getTodayText() {
  return getDateText(new Date());
}

// 오늘 요일을 한글 한 글자로 가져옵니다.
function getTodayDayName() {
  return ["일", "월", "화", "수", "목", "금", "토"][new Date().getDay()];
}

// 날짜값에서 실제 요일을 구합니다.
function getDayNameFromDateText(dateText) {
  if (!dateText) return "";

  const date = new Date(`${dateText}T00:00:00`);
  return ["일", "월", "화", "수", "목", "금", "토"][date.getDay()];
}

// 선택한 보기 날짜가 포함된 주를 기준으로 요일의 실제 날짜를 구합니다.
function getDateTextForDay(dayName) {
  const targetDayIndex = days.indexOf(dayName);
  const baseDate = new Date(`${selectedBoardDateText || getTodayText()}T00:00:00`);
  const baseDayIndex = baseDate.getDay();
  const mondayOffset = baseDayIndex === 0 ? 1 : 1 - baseDayIndex;
  const monday = new Date(baseDate);

  monday.setDate(baseDate.getDate() + mondayOffset);
  monday.setHours(0, 0, 0, 0);

  const targetDate = new Date(monday);
  targetDate.setDate(monday.getDate() + targetDayIndex);

  return getDateText(targetDate);
}

// 선택한 날짜가 월~토이면 폼의 요일도 실제 요일로 맞춥니다.
function syncDayInputWithDate() {
  const dayName = getDayNameFromDateText(dateInput.value);

  if (days.includes(dayName)) {
    dayInput.value = dayName;
  }
}

// 오늘이 월~토이면 오늘 요일을, 일요일이면 월요일을 기본값으로 사용합니다.
function getDefaultFormDay() {
  const selectedDayName = getDayNameFromDateText(selectedBoardDateText);
  return days.includes(selectedDayName) ? selectedDayName : "월";
}

// 현재 보드에서 강조할 요일입니다. 선택한 날짜가 월~토가 아니면 오늘 기준으로 봅니다.
function getFocusedBoardDayName() {
  const selectedDayName = getDayNameFromDateText(selectedBoardDateText);

  if (days.includes(selectedDayName)) {
    return selectedDayName;
  }

  const todayDayName = getTodayDayName();
  return days.includes(todayDayName) ? todayDayName : "월";
}

// 오늘 남아 있는 하원 일정 중 가장 가까운 일정을 찾습니다.
function getNextPickupSchedule(now) {
  const todayText = getDateText(now);

  return schedules
    .map(normalizeSchedule)
    .filter((schedule) => schedule.date === todayText && schedule.endTime)
    .map((schedule) => ({
      ...schedule,
      pickupDate: new Date(`${schedule.date}T${schedule.endTime}:00`),
    }))
    .filter((schedule) => schedule.pickupDate > now)
    .sort((first, second) => first.pickupDate - second.pickupDate)[0];
}

// 밀리초 차이를 "2시간 10분 5초"처럼 읽기 쉽게 바꿉니다.
function formatRemainingTime(milliseconds) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  if (hours > 0) {
    return `${hours}시간 ${minutes}분 ${seconds}초`;
  }

  return `${minutes}분 ${seconds}초`;
}

// 하원까지 남은 시간에 따라 큰 알림 문구를 정합니다.
function getPickupAlertMessage(nextPickup, remainingMilliseconds) {
  if (!nextPickup) return "";

  const remainingMinutes = Math.ceil(remainingMilliseconds / 60000);

  if (remainingMinutes <= 10) {
    return `${nextPickup.academy} 하원 10분 전입니다. 바로 준비해 주세요.`;
  }

  if (remainingMinutes <= 30) {
    return `${nextPickup.academy} 하원 30분 전입니다. 이동 준비를 시작해 주세요.`;
  }

  if (remainingMinutes <= 60) {
    return `${nextPickup.academy} 하원 1시간 전입니다. 시간을 확인해 주세요.`;
  }

  return "";
}

// 상단에 현재 날짜, 시간, 하원까지 남은 시간을 실시간으로 표시합니다.
function updateHeaderStatus() {
  const now = new Date();
  currentDate.textContent = new Intl.DateTimeFormat("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(now);
  currentTime.textContent = new Intl.DateTimeFormat("ko-KR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(now);

  const nextPickup = getNextPickupSchedule(now);
  if (nextPickup) {
    const remainingMilliseconds = nextPickup.pickupDate - now;
    const remainingTime = formatRemainingTime(remainingMilliseconds);
    const alertMessage = getPickupAlertMessage(nextPickup, remainingMilliseconds);

    pickupCountdown.textContent = `${nextPickup.academy} 하원까지 ${remainingTime}`;
    pickupCountdown.classList.toggle("warning", Boolean(alertMessage));

    if (alertMessage) {
      pickupAlert.hidden = false;
      pickupAlert.textContent = alertMessage;
    } else {
      pickupAlert.hidden = true;
      pickupAlert.textContent = "";
    }

    return;
  }

  const todayHasSchedule = schedules
    .map(normalizeSchedule)
    .some((schedule) => schedule.date === getDateText(now));

  pickupCountdown.textContent = todayHasSchedule ? "오늘 하원 일정 완료" : "오늘은 도보하원";
  pickupCountdown.classList.remove("warning");
  pickupAlert.hidden = true;
  pickupAlert.textContent = "";
}

// 일정 배열을 저장합니다. Firestore가 가능하면 가족 공유 저장소에, 실패하면 LocalStorage에 저장합니다.
function saveSchedules() {
  saveSchedulesToLocalStorage(schedules);
}

// 새 일정을 저장소에 추가합니다.
async function addScheduleToStorage(scheduleData) {
  const duplicateSchedule = findDuplicateSchedule(scheduleData);

  if (duplicateSchedule) {
    console.info("같은 일정이 이미 있어 중복 등록하지 않았습니다.");
    return duplicateSchedule;
  }

  if (isFirestoreReady && firestoreSchedulesCollection && firestoreApi) {
    try {
      const documentId = getScheduleDocumentId(scheduleData);
      const documentRef = firestoreApi.doc(firestoreDb, firestoreCollectionName, documentId);
      await firestoreApi.setDoc(documentRef, getScheduleDataForFirestore(scheduleData));
      const savedSchedule = {
        ...scheduleData,
        id: documentId,
      };

      schedules.push(savedSchedule);
      saveSchedulesToLocalStorage(schedules);
      return savedSchedule;
    } catch (error) {
      console.warn("Firestore 등록 실패로 LocalStorage에 저장합니다.", error);
      isFirestoreReady = false;
    }
  }

  schedules.push(scheduleData);
  saveSchedulesToLocalStorage(schedules);
  return scheduleData;
}

// 기존 일정을 저장소에서 수정합니다.
async function updateScheduleInStorage(scheduleData) {
  if (isFirestoreReady && firestoreDb && firestoreApi) {
    try {
      await firestoreApi.setDoc(
        firestoreApi.doc(firestoreDb, firestoreCollectionName, String(scheduleData.id)),
        getScheduleDataForFirestore(scheduleData)
      );
      schedules = schedules.map((schedule) => (String(schedule.id) === String(scheduleData.id) ? scheduleData : schedule));
      saveSchedulesToLocalStorage(schedules);
      return;
    } catch (error) {
      console.warn("Firestore 수정 실패로 LocalStorage에 저장합니다.", error);
      isFirestoreReady = false;
    }
  }

  schedules = schedules.map((schedule) => (String(schedule.id) === String(scheduleData.id) ? scheduleData : schedule));
  saveSchedulesToLocalStorage(schedules);
}

// 일정을 저장소에서 삭제합니다.
async function deleteScheduleFromStorage(id) {
  if (isFirestoreReady && firestoreDb && firestoreApi) {
    try {
      await firestoreApi.deleteDoc(firestoreApi.doc(firestoreDb, firestoreCollectionName, String(id)));
      schedules = schedules.filter((schedule) => String(schedule.id) !== String(id));
      saveSchedulesToLocalStorage(schedules);
      return;
    } catch (error) {
      console.warn("Firestore 삭제 실패로 LocalStorage에서 삭제합니다.", error);
      isFirestoreReady = false;
    }
  }

  schedules = schedules.filter((schedule) => String(schedule.id) !== String(id));
  saveSchedulesToLocalStorage(schedules);
}

// 선택한 요일에 일정 등록창을 엽니다.
function openForm(day = getDefaultFormDay()) {
  form.reset();
  editIdInput.value = "";
  dayInput.value = day;
  dateInput.value = getDateTextForDay(day);
  startTimeInput.value = "15:00";
  endTimeInput.value = "17:00";
  submitButton.textContent = "등록";
  dialog.showModal();
  academyInput.focus();
}

// 기존 일정을 수정할 수 있도록 입력창에 값을 채워 넣습니다.
function openEditForm(id) {
  const savedSchedule = schedules.find((item) => String(item.id) === String(id));
  if (!savedSchedule) return;

  const schedule = normalizeSchedule(savedSchedule);

  editIdInput.value = schedule.id;
  dayInput.value = schedule.day;
  dateInput.value = schedule.date;
  startTimeInput.value = schedule.startTime;
  endTimeInput.value = schedule.endTime;
  academyTypeInput.value = schedule.academyType;
  academyInput.value = schedule.academy;
  managerPhoneInput.value = schedule.managerPhone;
  academyPhoneInput.value = schedule.academyPhone;
  academyUrlInput.value = schedule.academyUrl;
  dropoffPlaceInput.value = schedule.dropoffPlace;
  memoInput.value = schedule.memo;
  submitButton.textContent = "수정";

  dialog.showModal();
  academyInput.focus();
}

// 기존 일정을 복사해서 새 일정으로 등록할 수 있게 입력창을 채웁니다.
function openCopyForm(id) {
  const savedSchedule = schedules.find((item) => String(item.id) === String(id));
  if (!savedSchedule) return;

  const schedule = normalizeSchedule(savedSchedule);

  editIdInput.value = "";
  dayInput.value = schedule.day;
  dateInput.value = getDateTextForDay(schedule.day);
  startTimeInput.value = schedule.startTime;
  endTimeInput.value = schedule.endTime;
  academyTypeInput.value = schedule.academyType;
  academyInput.value = schedule.academy;
  managerPhoneInput.value = schedule.managerPhone;
  academyPhoneInput.value = schedule.academyPhone;
  academyUrlInput.value = schedule.academyUrl;
  dropoffPlaceInput.value = schedule.dropoffPlace;
  memoInput.value = schedule.memo;
  submitButton.textContent = "복사 등록";

  dialog.showModal();
  dateInput.focus();
}

// 요일별로 칸의 색상을 다르게 지정합니다.
function getDayColorClass(day) {
  if (day === "토") return "saturday";
  return "weekday";
}

// 예전에 저장한 일정도 새 화면에서 보이도록 기본값을 맞춥니다.
function normalizeSchedule(schedule) {
  const savedDay = days.includes(schedule.day) ? schedule.day : getDayNameFromDateText(schedule.date);
  const normalizedDay = days.includes(savedDay) ? savedDay : "월";

  return {
    ...schedule,
    day: normalizedDay,
    date: getDateTextForDay(normalizedDay),
    startTime: schedule.startTime || schedule.time || "",
    endTime: schedule.endTime || "",
    academyType: schedule.academyType || schedule.character || "기타",
    academy: schedule.academy || schedule.title || "이름 없는 일정",
    managerPhone: schedule.managerPhone || "",
    academyPhone: schedule.academyPhone || "",
    academyUrl: schedule.academyUrl || "",
    dropoffPlace: schedule.dropoffPlace || "",
    memo: schedule.memo || "",
  };
}

// 전화 링크에는 숫자와 + 기호만 남깁니다.
function getPhoneHref(phoneNumber) {
  return `tel:${phoneNumber.replace(/[^0-9+]/g, "")}`;
}

// 홈페이지 주소는 http 또는 https 주소만 연결합니다.
function getSafeUrl(url) {
  try {
    const parsedUrl = new URL(url);
    if (parsedUrl.protocol === "http:" || parsedUrl.protocol === "https:") {
      return parsedUrl.href;
    }
  } catch (error) {
    return "";
  }

  return "";
}

// 요일 칸 하나를 만듭니다.
function createDayColumn(day) {
  const columnDate = getDateTextForDay(day);
  const daySchedules = getUniqueSchedules(schedules)
    .map(normalizeSchedule)
    .filter((schedule) => schedule.day === day && schedule.date === columnDate)
    .sort((first, second) => first.startTime.localeCompare(second.startTime));

  const column = document.createElement("section");
  column.className = `day-column ${getDayColorClass(day)}`;
  column.style.setProperty("--mobile-order", days.indexOf(day) + 1);
  if (day === getFocusedBoardDayName()) {
    column.classList.add("today");
    column.style.setProperty("--mobile-order", 0);

    if (selectedBoardDateText !== getTodayText()) {
      column.classList.add("selected-date");
    }
  }

  column.innerHTML = `
    <div class="day-header">
      <div>
        <div class="day-title">${day}요일</div>
        <div class="day-date">${formatDate(columnDate)}</div>
      </div>
    </div>
    <div class="schedule-list"></div>
  `;

  const list = column.querySelector(".schedule-list");

  if (daySchedules.length === 0) {
    list.innerHTML = `
      <div class="empty-message">
        <span class="walking-icon" aria-hidden="true">🚶</span>
        <span>
          <span class="empty-title">도보하원</span>
          <span class="empty-subtitle">등록된 학원 일정이 없습니다</span>
        </span>
      </div>
    `;
    return column;
  }

  daySchedules.forEach((schedule) => {
    const card = document.createElement("article");
    card.className = "schedule-card";

    // 사용자가 입력한 글자는 textContent로 넣어 HTML로 해석되지 않게 합니다.
    card.innerHTML = `
      <div class="schedule-row">
        <div class="schedule-title schedule-title-main">
          <div class="title-wrap">
            <span class="academy-type-badge"></span>
            <span class="academy-name"></span>
          </div>
          <details class="card-menu">
            <summary aria-label="일정 메뉴">⋯</summary>
            <div class="card-menu-list">
              <button class="copy-button menu-button" type="button">복사</button>
              <button class="edit-button menu-button" type="button">수정</button>
              <button class="delete-button menu-button" type="button">삭제</button>
            </div>
          </details>
        </div>
      </div>
      <div class="schedule-row">
        <div class="schedule-time-box">
          <div class="start-time-cell">
            <span class="time-label">등원</span>
            <div class="start-time schedule-time"></div>
          </div>
          <div class="end-time-cell">
            <span class="time-label">하원</span>
            <div class="end-time schedule-time"></div>
          </div>
        </div>
      </div>
      <div class="schedule-row schedule-detail"></div>
      <div class="card-actions">
      </div>
    `;

    card.querySelector(".start-time").textContent = schedule.startTime;
    card.querySelector(".end-time").textContent = schedule.endTime || "미정";
    card.querySelector(".academy-type-badge").textContent = schedule.academyType;
    card.querySelector(".academy-name").textContent = schedule.academy;

    const detail = card.querySelector(".schedule-detail");
    if (schedule.managerPhone) {
      const managerPhone = document.createElement("a");
      managerPhone.className = "phone-link";
      managerPhone.href = getPhoneHref(schedule.managerPhone);
      managerPhone.title = `하원도우미 ${schedule.managerPhone}`;
      managerPhone.setAttribute("aria-label", "하원도우미 전화 걸기");
      managerPhone.innerHTML = `<span class="action-label">하원도우미</span><span class="phone-icon" aria-hidden="true">☎</span>`;
      detail.appendChild(managerPhone);
    }

    if (schedule.academyPhone) {
      const academyPhone = document.createElement("a");
      academyPhone.className = "phone-link";
      academyPhone.href = getPhoneHref(schedule.academyPhone);
      academyPhone.title = `학원 ${schedule.academyPhone}`;
      academyPhone.innerHTML = `<span class="action-label">학원</span><span class="phone-icon" aria-hidden="true">☎</span>`;
      detail.appendChild(academyPhone);
    }

    if (schedule.academyUrl) {
      const safeUrl = getSafeUrl(schedule.academyUrl);

      if (safeUrl) {
        const academyUrl = document.createElement("a");
        academyUrl.className = "homepage-icon-link";
        academyUrl.target = "_blank";
        academyUrl.rel = "noreferrer";
        academyUrl.href = safeUrl;
        academyUrl.title = "학원홈페이지";
        academyUrl.innerHTML = `<span class="action-label">홈페이지</span><span class="homepage-icon" aria-hidden="true">⌂</span>`;
        academyUrl.setAttribute("aria-label", "홈페이지 열기");

        detail.appendChild(academyUrl);
      }
    }

    if (detail.children.length === 0) {
      detail.hidden = true;
    }

    const copyButton = card.querySelector(".copy-button");
    const editButton = card.querySelector(".edit-button");
    const deleteButton = card.querySelector(".delete-button");
    copyButton.addEventListener("click", () => openCopyForm(schedule.id));
    editButton.addEventListener("click", () => openEditForm(schedule.id));
    deleteButton.addEventListener("click", () => deleteSchedule(schedule.id));
    list.appendChild(card);
  });

  return column;
}

// 전체 칸반보드를 다시 그립니다.
function renderBoard() {
  schedules = saveSchedulesToLocalStorage(schedules);
  board.innerHTML = "";
  days.forEach((day) => {
    board.appendChild(createDayColumn(day));
  });
}

// 새 일정을 추가하거나 기존 일정을 수정합니다.
async function saveScheduleFromForm(event) {
  event.preventDefault();

  if (submitButton.disabled) {
    return;
  }

  submitButton.disabled = true;

  const editId = editIdInput.value;
  const selectedDate = dateInput.value || getDateTextForDay(dayInput.value);
  const dateDayName = getDayNameFromDateText(selectedDate);
  const scheduleData = {
    id: editId || String(Date.now()),
    day: days.includes(dateDayName) ? dateDayName : dayInput.value,
    date: selectedDate,
    startTime: startTimeInput.value,
    endTime: endTimeInput.value,
    academyType: academyTypeInput.value.trim(),
    academy: academyInput.value.trim(),
    managerPhone: managerPhoneInput.value.trim(),
    academyPhone: academyPhoneInput.value.trim(),
    academyUrl: academyUrlInput.value.trim(),
    dropoffPlace: dropoffPlaceInput.value.trim(),
    memo: memoInput.value.trim(),
  };

  try {
    if (firestoreStorageReadyPromise) {
      await firestoreStorageReadyPromise;
    }

    if (editId) {
      await updateScheduleInStorage(scheduleData);
    } else {
      const savedSchedule = await addScheduleToStorage(scheduleData);
      if (isFirestoreReady) {
        scheduleData.id = savedSchedule.id;
      }
    }

    renderBoard();
    updateHeaderStatus();
    dialog.close();
  } finally {
    submitButton.disabled = false;
  }
}

// 선택한 일정을 삭제합니다.
async function deleteSchedule(id) {
  await deleteScheduleFromStorage(id);
  renderBoard();
  updateHeaderStatus();
}

// 공유하기 버튼을 누르면 가능한 경우 공유창을 열고, 아니면 주소를 복사합니다.
async function sharePage() {
  const shareData = {
    title: "학원 스케줄 관리",
    text: "학원 스케줄 관리 페이지를 확인해 주세요.",
    url: window.location.href,
  };

  if (navigator.share) {
    await navigator.share(shareData);
    return;
  }

  if (navigator.clipboard) {
    await navigator.clipboard.writeText(window.location.href);
    sharePageButton.textContent = "링크 복사됨";
    setTimeout(() => {
      sharePageButton.textContent = "공유하기";
    }, 1600);
    return;
  }

  window.prompt("아래 주소를 복사해 주세요.", window.location.href);
}

openAddFormButton.addEventListener("click", () => openForm());
boardDateInput.value = selectedBoardDateText;
boardDateInput.addEventListener("change", () => {
  selectedBoardDateText = boardDateInput.value || getTodayText();
  renderBoard();
});
dayInput.addEventListener("change", () => {
  dateInput.value = getDateTextForDay(dayInput.value);
});
dateInput.addEventListener("change", syncDayInputWithDate);
sharePageButton.addEventListener("click", () => {
  sharePage().catch(() => {
    window.prompt("아래 주소를 복사해 주세요.", window.location.href);
  });
});
closeFormButton.addEventListener("click", () => dialog.close());
cancelFormButton.addEventListener("click", () => dialog.close());
form.addEventListener("submit", saveScheduleFromForm);

updateHeaderStatus();
setInterval(updateHeaderStatus, 1000);
renderBoard();
firestoreStorageReadyPromise = initializeFirestoreStorage();
